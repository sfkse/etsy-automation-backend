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


_SECTION_NAMES: dict["CarrierPillar", str] = {
    CarrierPillar.CROSS:        "Cross Necklaces",
    CarrierPillar.NAME:         "Name Necklaces",
    CarrierPillar.BIRTHSTONE:   "Birthstone Jewelry",
    CarrierPillar.BIRTH_FLOWER: "Birth Flower Jewelry",
    CarrierPillar.PET:          "Pet Jewelry",
    CarrierPillar.PENDANT:      "Pendant Necklaces",
}

_DEFAULT_ATTRIBUTES: dict["CarrierPillar", dict] = {
    CarrierPillar.CROSS: {
        "style": "Minimalist",
        "material": "925 Sterling Silver", # TODO: Check if 925 should be used or not
        "occasion": "Religious",
    },
    CarrierPillar.NAME: {
        "style": "Personalized",
        "material": "925 Sterling Silver",
        "occasion": "Birthday",
    },
    CarrierPillar.BIRTHSTONE: {
        "style": "Personalized",
        "material": "925 Sterling Silver",
        "has_stone": True,
    },
    CarrierPillar.BIRTH_FLOWER: {
        "style": "Floral",
        "material": "925 Sterling Silver",
        "occasion": "Birthday",
    },
    CarrierPillar.PET: {
        "style": "Personalized",
        "material": "925 Sterling Silver",
        "occasion": "Pet Memorial",
    },
    CarrierPillar.PENDANT: {
        "style": "Minimalist",
        "material": "925 Sterling Silver",
        "occasion": "Everyday",
    },
}


def get_section_name(pillar: "CarrierPillar") -> str:
    """Return the Etsy section name for a given carrier pillar."""
    return _SECTION_NAMES[pillar]


def get_default_attributes(pillar: "CarrierPillar") -> dict:
    """Return common default attributes for a given carrier pillar."""
    return dict(_DEFAULT_ATTRIBUTES[pillar])
