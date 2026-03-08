"""
schema/guide_rules.py - Guide 선택 규칙

Step에 여러 Guide가 연결된 경우, 현재 상태(protocolMode 등)에 따라
적절한 Guide를 선택하기 위한 매핑.
"""
from __future__ import annotations

# Guide 선택을 위한 protocolMode/조건 매핑
# Step에 여러 Guide가 연결된 경우, 현재 상태에 따라 적절한 Guide 선택
GUIDE_SELECTION_RULES = {
    # Persona 1: protocolMode 기반 Guide 선택
    "p1InformSurgery": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandard"],
            "LOW-FAT": ["guideLowFat"],
        },
    },
    # Persona 4: protocolMode 기반 Guide 선택 (여러 Step에 적용)
    "p4PreCollect": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardPremise"],
            "SEMI-REMOTE": ["guideSemiremotePremise"],
            "FULL": ["guideAbroadPremise"],
        },
    },
    "p4Collect": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardInbody"],
            "SEMI-REMOTE": ["guideSemiremoteInbody"],
            "FULL": ["guideAbroadInbody"],
        },
    },
    "p4AskLifestyle": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardRecovery"],
            "SEMI-REMOTE": ["guideSemiremoteLogic"],
            "FULL": ["guideAbroadLogic"],
        },
    },
    "p4AskDetail": {
        "conditionVar": "protocolMode",
        "mapping": {
            "SEMI-REMOTE": ["guideSemiremoteProcess"],
            "FULL": ["guideAbroadProcess"],
        },
    },
    "p4InformSurgery": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardProcess"],
            "SEMI-REMOTE": ["guideSemiremoteRoute"],
            "FULL": ["guideAbroadProtocol"],
        },
    },
    "p4InformInfo": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardUpload"],
            "SEMI-REMOTE": ["guideSemiremoteUpload"],
            "FULL": ["guideAbroadUpload"],
        },
    },
    "p4Confirm": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardBooking"],
            "SEMI-REMOTE": ["guideSemiremoteBooking"],
            "FULL": ["guideAbroadBooking"],
        },
    },
    "p4Finalize": {
        "conditionVar": "protocolMode",
        "mapping": {
            "STANDARD": ["guideStandardPostCare"],
            "SEMI-REMOTE": ["guideSemiremotePostCare"],
            "FULL": ["guideAbroadPostCare"],
        },
    },
}
