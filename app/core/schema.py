"""Pydantic schemas for validated LLM extractions.

Rule: any field the model cannot ground in the source/research is the
string ``"undefined"`` — never invented. Defaults enforce this even if
the model omits a field entirely.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

UNDEFINED = "undefined"


class CharacterSheet(BaseModel):
    gender: str = UNDEFINED
    species: str = Field(default=UNDEFINED, description="Race or species, e.g. human, fox, robot")
    age: str = UNDEFINED
    height: str = UNDEFINED
    build: str = UNDEFINED
    hair: str = UNDEFINED
    eyes: str = UNDEFINED
    skin: str = UNDEFINED
    attire: str = Field(default=UNDEFINED, description="Typical clothing and accessories")
    distinctive_traits: str = Field(default=UNDEFINED, description="Scars, props, mannerisms, anything visually identifying")


class Character(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    role: str = Field(default=UNDEFINED, description="protagonist, antagonist, supporting...")
    physical_description: str = Field(default=UNDEFINED, description="Full visual description as grounded in the source")
    sheet: CharacterSheet = Field(default_factory=CharacterSheet)


class Location(BaseModel):
    name: str
    description: str = UNDEFINED
    relevance: str = Field(default=UNDEFINED, description="Why this place matters to the story")


class Passage(BaseModel):
    title: str
    passage_type: str = Field(default=UNDEFINED, description="introduction, key event, climax, death, ending...")
    summary: str = UNDEFINED
    characters_present: list[str] = Field(default_factory=list)
    location: str = UNDEFINED


class BookExtraction(BaseModel):
    title: str = UNDEFINED
    author: str = UNDEFINED
    publication_year: str = UNDEFINED
    genre: str = UNDEFINED
    original_language: str = UNDEFINED
    themes: list[str] = Field(default_factory=list)
    summary: str = UNDEFINED
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
