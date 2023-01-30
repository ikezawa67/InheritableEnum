import sys
from types import MappingProxyType, DynamicClassAttribute


__all__ = ['EnumMeta', 'Enum', 'IntEnum', 'Flag', 'IntFlag', 'StrEnum', 'auto', 'unique',]


def _is_descriptor(obj):
    """
    Returns True if obj is a descriptor, False otherwise.
    """
    return (hasattr(obj, '__get__') or hasattr(obj, '__set__') or hasattr(obj, '__delete__'))


def _is_dunder(name):
    """
    Returns True if a __dunder__ name, False otherwise.
    """
    return (len(name) > 4 and name[:2] == name[-2:] == '__' and name[2] != '_' and name[-3] != '_')


def _is_sunder(name):
    """
    Returns True if a _sunder_ name, False otherwise.
    """
    return (len(name) > 2 and name[0] == name[-1] == '_' and name[1:2] != '_' and name[-2:-1] != '_')


def _make_class_unpicklable(cls):
    """
    Make the given class un-picklable.
    """

    def _break_on_call_reduce(self, proto):
        raise TypeError('%r cannot be pickled' % self)
    cls.__reduce_ex__ = _break_on_call_reduce
    cls.__module__ = '<unknown>'


_auto_null = object()


class auto:
    """
    Instances are replaced with an appropriate value in Enum class suites.
    """
    value = _auto_null


class _EnumDict(dict):
    """
    Track enum member order and ensure member names are not reused.

    EnumMeta will use the names found in self._member_names as the
    enumeration member names.
    """

    def __init__(self):
        super().__init__()
        self._member_names = []
        self._last_values = []
        self._ignore = []
        self._auto_called = False

    def __setitem__(self, key, value):
        """
        Changes anything not dundered or not a descriptor.

        If an enum member name is used twice, an error is raised; duplicate
        values are not checked for.

        Single underscore (sunder) names are reserved.
        """
        if _is_sunder(key):
            if key not in ('_order_', '_create_pseudo_member_', '_generate_next_value_', '_missing_', '_ignore_',):
                raise ValueError('_names_ are reserved for future Enum use')
            if key == '_generate_next_value_':
                if self._auto_called:
                    raise TypeError("_generate_next_value_ must be defined before members")
                setattr(self, '_generate_next_value', value)
            elif key == '_ignore_':
                if isinstance(value, str):
                    value = value.replace(',', ' ').split()
                else:
                    value = list(value)
                self._ignore = value
                already = set(value) & set(self._member_names)
                if already:
                    raise ValueError('_ignore_ cannot specify already set names: %r' % (already, ))
        elif _is_dunder(key):
            if key == '__order__':
                key = '_order_'
        elif key in self._member_names:
            raise TypeError('Attempted to reuse key: %r' % key)
        elif key in self._ignore:
            pass
        elif not _is_descriptor(value):
            if key in self:
                raise TypeError('%r already defined as: %r' % (key, self[key]))
            if isinstance(value, auto):
                if value.value == _auto_null:
                    value.value = self._generate_next_value(key, 1, len(self._last_values[:]), self._last_values[:],)
                    self._auto_called = True
                value = value.value
            self._member_names.append(key)
            self._last_values.append(value)
        super().__setitem__(key, value)


Enum = None
_enumerates = None


class EnumMeta(type):
    """
    Metaclass for Enum
    """
    @classmethod
    def __prepare__(metacls, cls, bases, plan_to_inherit=None, **kwds):
        enum_dict = _EnumDict()
        enum_dict._cls_name = cls
        member_type, first_enum = metacls._get_mixins_(cls, bases)
        if first_enum is not None:
            enum_dict['_generate_next_value_'] = getattr(first_enum, '_generate_next_value_', None,)
        inherited_types = set()
        for base in bases:
            if Enum is not None and issubclass(base, Enum):
                for enum_member in base:
                    enum_dict[enum_member.name] = enum_member.value
                if _enumerates is not None:
                    for mro in base.__mro__:
                        if mro in _enumerates:
                            inherited_types.add(mro)
                            break
                if 1 < len(inherited_types):
                    raise TypeError("<enum %r> inherited enums of different types %r" % (cls, inherited_types))
        if plan_to_inherit is not None and Enum is not None:
            if issubclass(plan_to_inherit, Enum):
                if issubclass(plan_to_inherit, bases[-1]):
                    enum_dict._last_values = list(plan_to_inherit._value2member_map_.keys())
                else:
                    raise TypeError("<enum %r> inherited an enum of a different type than the %r it was supposed to inherit from." % (cls, plan_to_inherit.__mro__[1]))
        return enum_dict

    def __new__(metacls, cls, bases, classdict, **kwds):
        classdict.setdefault('_ignore_', []).append('_ignore_')
        ignore = classdict['_ignore_']
        for key in ignore:
            classdict.pop(key, None)
        member_type, first_enum = metacls._get_mixins_(cls, bases)
        __new__, save_new, use_args = metacls._find_new_(classdict, member_type, first_enum,)
        enum_members = {k: classdict[k] for k in classdict._member_names}
        for name in classdict._member_names:
            del classdict[name]
        _order_ = classdict.pop('_order_', None)
        invalid_names = set(enum_members) & {'mro', ''}
        if invalid_names:
            raise ValueError('Invalid enum member name: {0}'.format(','.join(invalid_names)))
        if '__doc__' not in classdict:
            classdict['__doc__'] = 'An enumeration.'
        enum_class = super().__new__(metacls, cls, bases, classdict)
        enum_class._member_names_ = []
        enum_class._member_map_ = {}
        enum_class._member_type_ = member_type
        enum_class._successor_ = set()
        dynamic_attributes = {k for c in enum_class.mro() for k, v in c.__dict__.items() if isinstance(v, DynamicClassAttribute)}
        enum_class._value2member_map_ = {}
        if '__reduce_ex__' not in classdict:
            if member_type is not object:
                methods = ('__getnewargs_ex__', '__getnewargs__', '__reduce_ex__', '__reduce__')
                if not any(m in member_type.__dict__ for m in methods):
                    if '__new__' in classdict:
                        _make_class_unpicklable(enum_class)
                    else:
                        sabotage = None
                        for chain in bases:
                            for base in chain.__mro__:
                                if base is object:
                                    continue
                                elif any(m in base.__dict__ for m in methods):
                                    sabotage = False
                                    break
                                elif '__new__' in base.__dict__:
                                    sabotage = True
                                    break
                            if sabotage is not None:
                                break
                        if sabotage:
                            _make_class_unpicklable(enum_class)
        for member_name in classdict._member_names:
            for base in bases:
                if Enum is not None and issubclass(base, Enum) and member_name in base.__members__:
                    enum_member = base[member_name]
                    value = enum_member._value_
                    for name, canonical_member in enum_class._member_map_.items():
                        if canonical_member._value_ == enum_member._value_:
                            enum_member = canonical_member
                            break
                    else:
                        enum_class._member_names_.append(member_name)
                    if member_name not in dynamic_attributes:
                        setattr(enum_class, member_name, enum_member)
                    enum_class._member_map_[member_name] = enum_member
                    try:
                        enum_class._value2member_map_[value] = enum_member
                        enum_member._successor_.add(enum_class)
                        break
                    except TypeError:
                        pass
            else:
                value = enum_members[member_name]
                if not isinstance(value, tuple):
                    args = (value, )
                else:
                    args = value
                if member_type is tuple:
                    args = (args, )
                if not use_args:
                    enum_member = __new__(enum_class)
                    if not hasattr(enum_member, '_value_'):
                        enum_member._value_ = value
                else:
                    enum_member = __new__(enum_class, *args)
                    if not hasattr(enum_member, '_value_'):
                        if member_type is object:
                            enum_member._value_ = value
                        else:
                            enum_member._value_ = member_type(*args)
                value = enum_member._value_
                enum_member._name_ = member_name
                enum_member.__objclass__ = enum_class
                enum_member.__init__(*args)
                for name, canonical_member in enum_class._member_map_.items():
                    if canonical_member._value_ == enum_member._value_:
                        enum_member = canonical_member
                        break
                else:
                    enum_class._member_names_.append(member_name)
                if member_name not in dynamic_attributes:
                    setattr(enum_class, member_name, enum_member)
                enum_class._member_map_[member_name] = enum_member
                try:
                    enum_class._value2member_map_[value] = enum_member
                except TypeError:
                    pass
        for name in ('__repr__', '__str__', '__format__', '__reduce_ex__'):
            if name in classdict:
                continue
            class_method = getattr(enum_class, name)
            obj_method = getattr(member_type, name, None)
            enum_method = getattr(first_enum, name, None)
            if obj_method is not None and obj_method is class_method:
                setattr(enum_class, name, enum_method)
        if Enum is not None:
            if save_new:
                enum_class.__new_member__ = __new__
            enum_class.__new__ = Enum.__new__
        if _order_ is not None:
            if isinstance(_order_, str):
                _order_ = _order_.replace(',', ' ').split()
            if _order_ != enum_class._member_names_:
                raise TypeError('member order does not match _order_')
        return enum_class

    def __bool__(self):
        """
        classes/types should always be True.
        """
        return True

    def __call__(cls, value, names=None, *, module=None, qualname=None, type=None, start=1, plan_to_inherit=None):
        """
        Either returns an existing member, or creates a new enum class.

        This method is used both when an enum class is given a value to match
        to an enumeration member (i.e. Color(3)) and for the functional API
        (i.e. Color = Enum('Color', names='RED GREEN BLUE')).

        When used for the functional API:

        `value` will be the name of the new class.

        `names` should be either a string of white-space/comma delimited names
        (values will start at `start`), or an iterator/mapping of name, value pairs.

        `module` should be set to the module this class is being created in;
        if it is not set, an attempt to find that module will be made, but if
        it fails the class will not be picklable.

        `qualname` should be set to the actual location this class can be found
        at in its module; by default it is set to the global scope. If this is
        not correct, unpickling will fail in some circumstances.

        `type`, if set, will be mixed in as the first base class.
        """
        if names is None:
            return cls.__new__(cls, value)
        return cls._create_(value, names, module=module, qualname=qualname, type=type, start=start, plan_to_inherit=plan_to_inherit,)

    def __contains__(cls, obj):
        if not isinstance(obj, Enum):
            raise TypeError("unsupported operand type(s) for 'in': '%s' and '%s'" % (type(obj).__qualname__, cls.__class__.__qualname__))
        return isinstance(obj, cls) and obj._name_ in cls._member_map_

    def __delattr__(cls, attr):
        if attr in cls._member_map_:
            raise AttributeError("%s: cannot delete Enum member." % cls.__name__)
        super().__delattr__(attr)

    def __dir__(self):
        return (['__class__', '__doc__', '__members__', '__module__'] + self._member_names_)

    def __getattr__(cls, name):
        """
        Return the enum member matching `name`

        We use __getattr__ instead of descriptors or inserting into the enum
        class' __dict__ in order to support `name` and `value` being both
        properties for enum members (which live in the class' __dict__) and
        enum members themselves.
        """
        if _is_dunder(name):
            raise AttributeError(name)
        try:
            return cls._member_map_[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(cls, name):
        return cls._member_map_[name]

    def __iter__(cls):
        """
        Returns members in definition order.
        """
        return (cls._member_map_[name] for name in cls._member_names_)

    def __len__(cls):
        return len(cls._member_names_)

    @property
    def __members__(cls):
        """
        Returns a mapping of member name->value.

        This mapping lists all enum members, including aliases. Note that this
        is a read-only view of the internal mapping.
        """
        return MappingProxyType(cls._member_map_)

    def __repr__(cls):
        return "<enum %r>" % cls.__name__

    def __reversed__(cls):
        """
        Returns members in reverse definition order.
        """
        return (cls._member_map_[name] for name in reversed(cls._member_names_))

    def __setattr__(cls, name, value):
        """
        Block attempts to reassign Enum members.

        A simple assignment to the class namespace only changes one of the
        several possible ways to get an Enum member from the Enum class,
        resulting in an inconsistent Enumeration.
        """
        member_map = cls.__dict__.get('_member_map_', {})
        if name in member_map:
            raise AttributeError('Cannot reassign members.')
        super().__setattr__(name, value)

    def _create_(cls, class_name, names, *, module=None, qualname=None, type=None, start=1, plan_to_inherit=None):
        """
        Convenience method to create a new Enum class.

        `names` can be:

        * A string containing member names, separated either with spaces or
         commas. Values are incremented by 1 from `start`.
        * An iterable of member names. Values are incremented by 1 from `start`.
        * An iterable of (member name, value) pairs.
        * A mapping of member name -> value pairs.
        """
        metacls = cls.__class__
        bases = (cls, ) if type is None else (type, cls)
        _, first_enum = cls._get_mixins_(cls, bases)
        classdict = metacls.__prepare__(class_name, bases, plan_to_inherit)
        if isinstance(names, str):
            names = names.replace(',', ' ').split()
        if isinstance(names, (tuple, list)) and names and isinstance(names[0], str):
            original_names, names = names, []
            last_values = []
            for count, name in enumerate(original_names):
                value = first_enum._generate_next_value_(name, start, count, last_values[:])
                last_values.append(value)
                names.append((name, value))
        for item in names:
            if isinstance(item, str):
                member_name, member_value = item, names[item]
            else:
                member_name, member_value = item
            classdict[member_name] = member_value
        enum_class = metacls.__new__(metacls, class_name, bases, classdict)
        if module is None:
            try:
                module = sys._getframe(2).f_globals['__name__']
            except (AttributeError, ValueError, KeyError):
                pass
        if module is None:
            _make_class_unpicklable(enum_class)
        else:
            enum_class.__module__ = module
        if qualname is not None:
            enum_class.__qualname__ = qualname
        return enum_class

    def _convert_(cls, name, module, filter, source=None):
        """
        Create a new Enum subclass that replaces a collection of global constants
        """
        module_globals = vars(sys.modules[module])
        if source:
            source = vars(source)
        else:
            source = module_globals
        members = [(name, value) for name, value in source.items() if filter(name)]
        try:
            members.sort(key=lambda t: (t[1], t[0]))
        except TypeError:
            members.sort(key=lambda t: t[0])
        cls = cls(name, members, module=module)
        cls.__reduce_ex__ = _reduce_ex_by_name
        module_globals.update(cls.__members__)
        module_globals[name] = cls
        return cls

    @staticmethod
    def _get_mixins_(class_name, bases):
        """
        Returns the type for creating enum members, and the first inherited
        enum class.

        bases: the tuple of bases that was given to __new__
        """
        if not bases:
            return object, Enum

        def _find_data_type(bases):
            data_types = set()
            for chain in bases:
                candidate = None
                for base in chain.__mro__:
                    if base is object:
                        continue
                    elif issubclass(base, Enum):
                        if base._member_type_ is not object:
                            data_types.add(base._member_type_)
                            break
                    elif '__new__' in base.__dict__:
                        if issubclass(base, Enum):
                            continue
                        data_types.add(candidate or base)
                        break
                    else:
                        candidate = candidate or base
            if len(data_types) > 1:
                raise TypeError('%r: too many data types: %r' % (class_name, data_types))
            elif data_types:
                return data_types.pop()
            else:
                return None
        first_enum = bases[-1]
        if not issubclass(first_enum, Enum):
            raise TypeError("new enumerations should be created as EnumName([mixin_type, ...] [data_type,] enum_type)`")
        member_type = _find_data_type(bases) or object
        return member_type, first_enum

    @staticmethod
    def _find_new_(classdict, member_type, first_enum):
        """
        Returns the __new__ to be used for creating the enum members.

        classdict: the class dictionary given to __new__
        member_type: the data type whose __new__ will be used by default
        first_enum: enumeration to check for an overriding __new__
        """
        __new__ = classdict.get('__new__', None)
        save_new = __new__ is not None
        if __new__ is None:
            for method in ('__new_member__', '__new__'):
                for possible in (member_type, first_enum):
                    target = getattr(possible, method, None)
                    if target not in {None, None.__new__, object.__new__, Enum.__new__, }:
                        __new__ = target
                        break
                if __new__ is not None:
                    break
            else:
                __new__ = object.__new__
        if __new__ is object.__new__:
            use_args = False
        else:
            use_args = True
        return __new__, save_new, use_args


class Enum(metaclass=EnumMeta):
    """
    Generic enumeration.

    Derive from this class to define new enumerations.
    """
    def __new__(cls, value):
        if type(value) is cls:
            return value
        try:
            return cls._value2member_map_[value]
        except KeyError:
            pass
        except TypeError:
            for member in cls._member_map_.values():
                if member._value_ == value:
                    return member
        try:
            exc = None
            result = cls._missing_(value)
        except Exception as e:
            exc = e
            result = None
        try:
            if isinstance(result, cls):
                return result
            else:
                ve_exc = ValueError("%r is not a valid %s" % (value, cls.__qualname__))
                if result is None and exc is None:
                    raise ve_exc
                elif exc is None:
                    exc = TypeError('error in %s._missing_: returned %r instead of None or a valid member' % (cls.__name__, result))
                if not isinstance(exc, ValueError):
                    exc.__context__ = ve_exc
                raise exc
        finally:
            exc = None
            ve_exc = None

    def _generate_next_value_(name, start, count, last_values):
        """
        Generate the next value when not given.

        name: the name of the member
        start: the initial start value or None
        count: the number of existing members
        last_value: the last value assigned or None
        """
        for last_value in reversed(last_values):
            try:
                return last_value + 1
            except TypeError:
                pass
        else:
            return start

    @classmethod
    def _missing_(cls, value):
        return None

    def __repr__(self):
        return "<%s.%s: %r>" % (
            self.__class__.__name__, self._name_, self._value_)

    def __str__(self):
        return "%s.%s" % (self.__class__.__name__, self._name_)

    def __dir__(self):
        """
        Returns all members and all public methods
        """
        added_behavior = [m for cls in self.__class__.mro() for m in cls.__dict__ if m[0] != '_' and m not in self._member_map_] + [m for m in self.__dict__ if m[0] != '_']
        return (['__class__', '__doc__', '__module__'] + added_behavior)

    def __format__(self, format_spec):
        """
        Returns format using actual value type unless __str__ has been overridden.
        """
        str_overridden = type(self).__str__ not in (Enum.__str__, Flag.__str__)
        if self._member_type_ is object or str_overridden:
            cls = str
            val = str(self)
        else:
            cls = self._member_type_
            val = self._value_
        return cls.__format__(val, format_spec)

    def __hash__(self):
        return hash(self._name_)

    def __reduce_ex__(self, proto):
        return self.__class__, (self._value_, )

    @DynamicClassAttribute
    def name(self):
        """The name of the Enum member."""
        return self._name_

    @DynamicClassAttribute
    def value(self):
        """The value of the Enum member."""
        return self._value_


class IntEnum(int, Enum):
    """Enum where members are also (and must be) ints"""


def _reduce_ex_by_name(self, proto):
    return self.name


class Flag(Enum):
    """
    Support for flags
    """

    def _generate_next_value_(name, start, count, last_values):
        """
        Generate the next value when not given.

        name: the name of the member
        start: the initial start value or None
        count: the number of existing members
        last_value: the last value assigned or None
        """
        if not count:
            return start if start is not None else 1
        for last_value in reversed(last_values):
            try:
                high_bit = _high_bit(last_value)
                break
            except Exception:
                raise TypeError('Invalid Flag value: %r' % last_value) from None
        return 2 ** (high_bit+1)

    @classmethod
    def _missing_(cls, value):
        """
        Returns member (possibly creating it) if one can be found for value.
        """
        original_value = value
        if value < 0:
            value = ~value
        possible_member = cls._create_pseudo_member_(value)
        if original_value < 0:
            possible_member = ~possible_member
        return possible_member

    @classmethod
    def _create_pseudo_member_(cls, value):
        """
        Create a composite member iff value contains only members.
        """
        pseudo_member = cls._value2member_map_.get(value, None)
        if pseudo_member is None:
            _, extra_flags = _decompose(cls, value)
            if extra_flags:
                raise ValueError("%r is not a valid %s" % (value, cls.__qualname__))
            pseudo_member = object.__new__(cls)
            pseudo_member._name_ = None
            pseudo_member._value_ = value
            pseudo_member = cls._value2member_map_.setdefault(value, pseudo_member)
        return pseudo_member

    def __contains__(self, other):
        """
        Returns True if self has at least the same flags set as other.
        """
        if not isinstance(other, self.__class__):
            raise TypeError("unsupported operand type(s) for 'in': '%s' and '%s'" % (type(other).__qualname__, self.__class__.__qualname__))
        return other._value_ & self._value_ == other._value_

    def __repr__(self):
        cls = self.__class__
        if self._name_ is not None:
            return '<%s.%s: %r>' % (cls.__name__, self._name_, self._value_)
        members, uncovered = _decompose(cls, self._value_)
        return '<%s.%s: %r>' % (cls.__name__,   '|'.join([str(m._name_ or m._value_) for m in members]),   self._value_,)

    def __str__(self):
        cls = self.__class__
        if self._name_ is not None:
            return '%s.%s' % (cls.__name__, self._name_)
        members, uncovered = _decompose(cls, self._value_)
        if len(members) == 1 and members[0]._name_ is None:
            return '%s.%r' % (cls.__name__, members[0]._value_)
        else:
            return '%s.%s' % (cls.__name__,    '|'.join([str(m._name_ or m._value_) for m in members]),)

    def __bool__(self):
        return bool(self._value_)

    def __or__(self, other):
        if issubclass(other.__class__, Enum) and issubclass(self.__class__, other.__class__):
            return self.__class__(self._value_ | other._value_)
        elif issubclass(other.__class__, self.__class__):
            return other.__class__(self._value_ | other._value_)
        elif self._member_type_ is not object and isinstance(other, self._member_type_):
            return self.__class__(self._value_ | other)
        else:
            for successor in self._successor_:
                if issubclass(successor, self.__class__) and issubclass(successor, other.__class__):
                    return successor(self._value_ | other._value_)
            else:
                return NotImplemented

    def __and__(self, other):
        if issubclass(other.__class__, Enum) and issubclass(self.__class__, other.__class__):
            return self.__class__(self._value_ & other._value_)
        elif issubclass(other.__class__, self.__class__):
            return other.__class__(self._value_ & other._value_)
        elif self._member_type_ is not object and isinstance(other, self._member_type_):
            return self.__class__(self._value_ & other)
        else:
            for successor in self._successor_:
                if issubclass(successor, self.__class__) and issubclass(successor, other.__class__):
                    return successor(self._value_ | other._value_)
            else:
                return NotImplemented

    def __xor__(self, other):
        if issubclass(other.__class__, Enum) and issubclass(self.__class__, other.__class__):
            return self.__class__(self._value_ ^ other._value_)
        elif issubclass(other.__class__, self.__class__):
            return other.__class__(self._value_ ^ other._value_)
        elif self._member_type_ is not object and isinstance(other, self._member_type_):
            return self.__class__(self._value_ ^ other)
        else:
            for successor in self._successor_:
                if issubclass(successor, self.__class__) and issubclass(successor, other.__class__):
                    return successor(self._value_ | other._value_)
            else:
                return NotImplemented

    def __invert__(self):
        members, uncovered = _decompose(self.__class__, self._value_)
        inverted = self.__class__(0)
        for m in self.__class__:
            if m not in members and not (m._value_ & self._value_):
                inverted = inverted | m
        return self.__class__(inverted)


class IntFlag(int, Flag):
    """
    Support for integer-based Flags
    """

    @classmethod
    def _missing_(cls, value):
        """
        Returns member (possibly creating it) if one can be found for value.
        """
        if not isinstance(value, int):
            raise ValueError("%r is not a valid %s" % (value, cls.__qualname__))
        new_member = cls._create_pseudo_member_(value)
        return new_member

    @classmethod
    def _create_pseudo_member_(cls, value):
        """
        Create a composite member iff value contains only members.
        """
        pseudo_member = cls._value2member_map_.get(value, None)
        if pseudo_member is None:
            need_to_create = [value]
            _, extra_flags = _decompose(cls, value)
            while extra_flags:
                bit = _high_bit(extra_flags)
                flag_value = 2 ** bit
                if (flag_value not in cls._value2member_map_ and flag_value not in need_to_create):
                    need_to_create.append(flag_value)
                if extra_flags == -flag_value:
                    extra_flags = 0
                else:
                    extra_flags ^= flag_value
            for value in reversed(need_to_create):
                pseudo_member = int.__new__(cls, value)
                pseudo_member._name_ = None
                pseudo_member._value_ = value
                pseudo_member = cls._value2member_map_.setdefault(value, pseudo_member)
        return pseudo_member

    def __or__(self, other):
        if not isinstance(other, (self.__class__, int)):
            return NotImplemented
        result = self.__class__(self._value_ | self.__class__(other)._value_)
        return result

    def __and__(self, other):
        if not isinstance(other, (self.__class__, int)):
            return NotImplemented
        return self.__class__(self._value_ & self.__class__(other)._value_)

    def __xor__(self, other):
        if not isinstance(other, (self.__class__, int)):
            return NotImplemented
        return self.__class__(self._value_ ^ self.__class__(other)._value_)

    __ror__ = __or__
    __rand__ = __and__
    __rxor__ = __xor__

    def __invert__(self):
        result = self.__class__(~self._value_)
        return result


def _high_bit(value):
    """
    returns index of highest bit, or -1 if value is zero or negative
    """
    return value.bit_length() - 1


class StrEnum(str, Enum):
    """
    Enum where members are also (and must be) strings
    """
    def __new__(cls, *values):
        "values must already be of type `str`"
        if len(values) > 3:
            raise TypeError('too many arguments for str(): %r' % (values, ))
        if len(values) == 1:
            if not isinstance(values[0], str):
                raise TypeError('%r is not a string' % (values[0], ))
        if len(values) >= 2:
            if not isinstance(values[1], str):
                raise TypeError('encoding must be a string, not %r' % (values[1], ))
        if len(values) == 3:
            if not isinstance(values[2], str):
                raise TypeError('errors must be a string, not %r' % (values[2]))
        value = str(*values)
        member = str.__new__(cls, value)
        member._value_ = value
        return member

    def _generate_next_value_(name, start, count, last_values):
        """
        Return the lower-cased version of the member name.
        """
        return name.lower()


def unique(enumeration):
    """
    Class decorator for enumerations ensuring unique member values.
    """
    duplicates = []
    for name, member in enumeration.__members__.items():
        if name != member.name:
            duplicates.append((name, member.name))
    if duplicates:
        alias_details = ', '.join(["%s -> %s" % (alias, name) for (alias, name) in duplicates])
        raise ValueError('duplicate values found in %r: %s' % (enumeration, alias_details))
    return enumeration


def _decompose(flag, value):
    """
    Extract all members from the value.
    """
    not_covered = value
    negative = value < 0
    members = []
    for member in flag:
        member_value = member.value
        if member_value and member_value & value == member_value:
            members.append(member)
            not_covered &= ~member_value
    if not negative:
        tmp = not_covered
        while tmp:
            flag_value = 2 ** _high_bit(tmp)
            if flag_value in flag._value2member_map_:
                members.append(flag._value2member_map_[flag_value])
                not_covered &= ~flag_value
            tmp &= ~flag_value
    if not members and value in flag._value2member_map_:
        members.append(flag._value2member_map_[value])
    members.sort(key=lambda m: m._value_, reverse=True)
    if len(members) > 1 and members[0].value == value:
        members.pop(0)
    return members, not_covered


_enumerates = [Enum, IntEnum, Flag, IntEnum, StrEnum]
