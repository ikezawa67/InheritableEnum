# InheritableEnum
PythonのEnumを継承し使用することを可能にしたモジュール
以下の列挙型が使用できる
* Enum
* IntEnum
* Flag
* IntFlag
* StrEnum 
## 必要要件
Python >= 3.4
## 使用法
```python
from inheritable_enum import *


class Dog(Flag):
    Beagle = auto()  # 1
    BassetHound = auto()  # 2


class Cat(Flag, plan_to_inherit=Dog):
    # 別の列挙型と一緒に継承する予定がある場合は、
    # plan_to_inheritに最も大きい値を使用している列挙型を与えることで、
    # auto()の値が続きの値から置き換わる
    Siamese = auto()  # 4
    Persian = auto()  # 8


Owl = Flag("Owl", {name: auto() for name in ["HornedOwl"]}, plan_to_inherit=Cat)
# 動的に宣言することも可能


@unique
class Pet(Dog, Cat, Owl):
    # 継承した列挙型にもメンバーを宣言可能
    Cow = auto()  # 32


pet = Dog.Beagle | Cat.Persian  # <Pet.Persian|Beagle: 9>
# 異なる列挙型でビット演算を行った場合は適切な列挙型に置き換えられる
print(bool(pet & Pet.Siamese))  # False
print(bool(pet & Dog.Beagle))  # True


@unique
class Rabbit(Flag):
    # plan_to_inheritを与えていないため値が1から置き換わる
    JapaneseWhite = auto()  # 1
    # auto()を使用せずに自身で値を宣言しているためFrenchLopは正常に使用可能
    FrenchLop = 128


class Animal(Pet, Rabbit):
    # デコレーターにuniqueを使用しないためBeagleとJapaneseWhiteが同じ値だが宣言可能
    pass


animal = Animal.JapaneseWhite | Pet.Beagle  # <Dog.Beagle: 1>
# 1 | 1 となってしまい名前が有効なBeagleが変数に返る
animal |= Rabbit.FrenchLop  # <Animal.FrenchLop|Beagle: 129>
print(bool(animal & Animal.FrenchLop))  # true
```
