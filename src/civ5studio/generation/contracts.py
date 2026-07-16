"""Verified generation order and BNW schema surface used by the compiler."""

from __future__ import annotations


DATABASE_FILE_ORDER = (
    "Core/Text.sql",
    "Core/Colors.sql",
    "Core/IconAtlases.sql",
    "Core/Trait.sql",
    "Core/Leader.sql",
    "Core/Units.sql",
    "Core/Buildings.sql",
    "Core/Improvements.sql",
    "Core/Civilization.sql",
)

MAIN_ATLAS_SIZES = (256, 128, 80, 64, 45, 32)
ALPHA_ATLAS_SIZES = (128, 80, 64, 48, 32, 24, 16)
ATLAS_GRID = (8, 8)
PORTRAIT_FIT_DIAMETER = 172
PORTRAIT_REFERENCE_SIZE = 256

DEFAULT_LEADER_FLAVORS = {
    "FLAVOR_OFFENSE": 5,
    "FLAVOR_DEFENSE": 5,
    "FLAVOR_EXPANSION": 5,
    "FLAVOR_GROWTH": 5,
    "FLAVOR_PRODUCTION": 5,
    "FLAVOR_GOLD": 5,
    "FLAVOR_SCIENCE": 5,
    "FLAVOR_CULTURE": 5,
    "FLAVOR_RELIGION": 5,
    "FLAVOR_DIPLOMACY": 5,
    "FLAVOR_WONDER": 4,
    "FLAVOR_MOBILE": 5,
}
DEFAULT_MAJOR_CIV_BIASES = {
    "MAJOR_CIV_APPROACH_WAR": 5,
    "MAJOR_CIV_APPROACH_HOSTILE": 5,
    "MAJOR_CIV_APPROACH_DECEPTIVE": 4,
    "MAJOR_CIV_APPROACH_GUARDED": 5,
    "MAJOR_CIV_APPROACH_AFRAID": 3,
    "MAJOR_CIV_APPROACH_FRIENDLY": 6,
    "MAJOR_CIV_APPROACH_NEUTRAL": 6,
}
DEFAULT_MINOR_CIV_BIASES = {
    "MINOR_CIV_APPROACH_IGNORE": 3,
    "MINOR_CIV_APPROACH_FRIENDLY": 6,
    "MINOR_CIV_APPROACH_PROTECTIVE": 5,
    "MINOR_CIV_APPROACH_CONQUEST": 4,
    "MINOR_CIV_APPROACH_BULLY": 4,
}


REQUIRED_SCHEMA = {
    "Language_en_US": {"Tag", "Text"},
    "Colors": {"Type", "Red", "Green", "Blue", "Alpha"},
    "PlayerColors": {"Type", "PrimaryColor", "SecondaryColor", "TextColor"},
    "IconTextureAtlases": {
        "Atlas", "IconSize", "Filename", "IconsPerRow", "IconsPerColumn"
    },
    "Traits": {
        "Type", "Description", "ShortDescription", "LevelExperienceModifier",
        "GreatPeopleRateModifier", "WorkerSpeedModifier", "WonderProductionModifier",
        "PlotBuyCostModifier", "LandTradeRouteRangeBonus",
        "TradeRouteResourceModifier", "ExtraEmbarkMoves",
        "CrossesMountainsAfterGreatGeneral",
    },
    "Leaders": {
        "Type", "Description", "Civilopedia", "CivilopediaTag", "ArtDefineTag",
        "VictoryCompetitiveness", "WonderCompetitiveness", "MinorCivCompetitiveness",
        "Boldness", "DiploBalance", "WarmongerHate", "DenounceWillingness",
        "DoFWillingness", "Loyalty", "Neediness", "Forgiveness", "Chattiness",
        "Meanness", "IconAtlas", "PortraitIndex",
    },
    "Leader_MajorCivApproachBiases": {"LeaderType", "MajorCivApproachType", "Bias"},
    "Leader_MinorCivApproachBiases": {"LeaderType", "MinorCivApproachType", "Bias"},
    "Leader_Flavors": {"LeaderType", "FlavorType", "Flavor"},
    "Leader_Traits": {"LeaderType", "TraitType"},
    "Diplomacy_Responses": {"LeaderType", "ResponseType", "Response", "Bias"},
    "Units": {
        "Type", "Class", "Description", "Help", "Strategy", "Civilopedia", "Combat",
        "RangedCombat", "Moves", "Cost", "PrereqTech", "UnitArtInfo", "UnitFlagAtlas",
        "UnitFlagIconOffset", "IconAtlas", "PortraitIndex",
    },
    "UnitGameplay2DScripts": {"UnitType", "SelectionSound", "FirstSelectionSound"},
    "Unit_AITypes": {"UnitType", "UnitAIType"},
    "Unit_Flavors": {"UnitType", "FlavorType", "Flavor"},
    "Unit_FreePromotions": {"UnitType", "PromotionType"},
    "Unit_ClassUpgrades": {"UnitType", "UnitClassType"},
    "ArtDefine_UnitInfos": {
        "Type", "DamageStates", "Formation", "UnitFlagAtlas",
        "UnitFlagIconOffset", "IconAtlas", "PortraitIndex",
    },
    "ArtDefine_UnitInfoMemberInfos": {
        "UnitInfoType", "UnitMemberInfoType", "NumMembers",
    },
    "ArtDefine_UnitMemberInfos": {
        "Type", "Scale", "ZOffset", "Domain", "Model",
        "MaterialTypeTag", "MaterialTypeSoundOverrideTag",
    },
    "ArtDefine_UnitMemberCombats": {"UnitMemberType"},
    "ArtDefine_UnitMemberCombatWeapons": {"UnitMemberType"},
    "ArtDefine_StrategicView": {"StrategicViewType", "TileType", "Asset"},
    "Buildings": {
        "Type", "BuildingClass", "Description", "Help", "Strategy", "Civilopedia",
        "Cost", "GoldMaintenance", "Defense", "ExtraCityHitPoints", "PrereqTech",
        "PortraitIndex", "IconAtlas", "ArtDefineTag",
    },
    "Building_ClassesNeededInCity": {"BuildingType", "BuildingClassType"},
    "Building_YieldChanges": {"BuildingType", "YieldType", "Yield"},
    "Building_DomainFreeExperiences": {"BuildingType", "DomainType", "Experience"},
    "Improvements": {
        "Type", "Description", "Civilopedia", "Help", "ArtDefineTag",
        "SpecificCivRequired", "CivilizationType", "PortraitIndex", "IconAtlas",
    },
    "Improvement_Yields": {"ImprovementType", "YieldType", "Yield"},
    "Builds": {
        "Type", "Description", "Help", "Recommendation", "PrereqTech",
        "ImprovementType", "IconIndex", "IconAtlas",
    },
    "BuildFeatures": {"BuildType"},
    "Build_TechTimeChanges": {"BuildType"},
    "Unit_Builds": {"UnitType", "BuildType"},
    "Civilizations": {
        "Type", "Description", "ShortDescription", "Adjective", "Civilopedia",
        "CivilopediaTag", "DefaultPlayerColor", "ArtDefineTag", "ArtStyleType",
        "ArtStyleSuffix", "ArtStylePrefix", "PortraitIndex", "IconAtlas",
        "AlphaIconAtlas", "SoundtrackTag", "MapImage", "DawnOfManQuote",
        "DawnOfManImage", "DawnOfManAudio",
    },
    "Audio_Sounds": {"SoundID", "FileName", "LoadType", "DontCache"},
    "Audio_2DSounds": {
        "ScriptID", "SoundID", "SoundType", "MaxVolume", "MinVolume", "IsMusic",
    },
    "Civilization_CityNames": {"CivilizationType", "CityName"},
    "Civilization_SpyNames": {"CivilizationType", "SpyName"},
    "Civilization_FreeBuildingClasses": {"CivilizationType", "BuildingClassType"},
    "Civilization_FreeTechs": {"CivilizationType", "TechType"},
    "Civilization_FreeUnits": {"CivilizationType", "UnitClassType", "Count", "UnitAIType"},
    "Civilization_Leaders": {"CivilizationType", "LeaderheadType"},
    "Civilization_UnitClassOverrides": {"CivilizationType", "UnitClassType", "UnitType"},
    "Civilization_BuildingClassOverrides": {
        "CivilizationType", "BuildingClassType", "BuildingType"
    },
    "Civilization_Start_Region_Avoid": {"CivilizationType", "RegionType"},
}
