"""
CarrierPillar enum — the six valid product categories.
"""
from enum import Enum


class CarrierPillar(str, Enum):
    CROSS = "cross"
    NAME = "name"
    BIRTHSTONE = "birthstone"
    BIRTH_FLOWER = "birth_flower"
    PET = "pet"
    PENDANT = "pendant"
