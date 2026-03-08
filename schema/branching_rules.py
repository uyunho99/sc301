"""
schema/branching_rules.py - 분기 규칙 매핑

실제 DB에서 Transition이 Step에 HAS_TRANSITION으로 연결되지 않으므로,
분기가 필요한 Step과 Transition/Rule을 매핑하는 정적 라우팅 테이블.
docx 온톨로지 기반 + 실제 DB 데이터 기준.
"""
from __future__ import annotations

# 각 분기점 Step에서의 Transition 규칙
# format: { sourceStepId: [ { transitionId, ruleId, targetStepId, priority, isDefault } ] }
BRANCHING_RULES = {
    # === Persona 1 (slimBody): BMI 기준 분기 ===
    # p1InformSurgery에서 bmi >= 23 (STANDARD) vs bmi < 23 (LOW-FAT)
    "p1InformSurgery": [
        {
            "transitionId": "bmiPathStandard",
            "ruleId": "ruleBodyFatHigh",
            "targetStepId": "p1InformInfo",  # STANDARD 경로
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "bmiPathLowFat",
            "ruleId": "ruleBodyFatLow",
            "targetStepId": "p1InformInfo",  # LOW-FAT 경로 (같은 Step, Guide가 다름)
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "bmiPathDefault",
            "ruleId": None,
            "targetStepId": "p1InformInfo",  # Default: BMI 계산 실패 시 STANDARD로 진행
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 2 (lipoCustomer): 흡입 단독 vs 흡입+이식 분기 ===
    # p2InformSurgery에서 upsellAccept 기반 분기
    "p2InformSurgery": [
        {
            "transitionId": "lipoOnly",
            "ruleId": None,  # condLipoOnly (upsellAccept = false)
            "conditionVar": "upsellAccept",
            "conditionOp": "=",
            "conditionRef": "false",
            "targetStepId": "p2InformInfoA",  # 흡입 단독
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "lipoPlusTransfer",
            "ruleId": None,  # condLipoPlusTransfer (upsellAccept = true)
            "conditionVar": "upsellAccept",
            "conditionOp": "=",
            "conditionRef": "true",
            "targetStepId": "p2InformInfoB",  # 흡입+이식
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "lipoDefault",
            "ruleId": None,
            "targetStepId": "p2InformInfoA",  # 기본: 흡입 단독 경로
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 2 (lipoCustomer): 일반 vs 줄기세포 분기 (p2InformInfoB 이후) ===
    "p2InformInfoB": [
        {
            "transitionId": "chooseGeneral",
            "ruleId": None,
            "conditionVar": "transferType",
            "conditionOp": "=",
            "conditionRef": "일반",
            "targetStepId": "p2Finalize",
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "chooseStemCell",
            "ruleId": None,
            "conditionVar": "transferType",
            "conditionOp": "=",
            "conditionRef": "줄기세포",
            "targetStepId": "p2Finalize",
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "chooseDefaultUndecided",
            "ruleId": None,
            "targetStepId": "p2Finalize",
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 4 (longDistance): 거주지 기반 프로토콜 분기 ===
    # p4PreCollect에서 residenceCountry / regionBucket 기반 분기
    "p4PreCollect": [
        {
            "transitionId": "regionPathAbroad",
            "ruleId": "ruleRegionRemote",
            "targetStepId": "p4Collect",  # FULL 프로토콜 (해외)
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "regionPathSemiRemote",
            "ruleId": "ruleRegionSemiRemote",
            "targetStepId": "p4Collect",  # SEMI-REMOTE 프로토콜 (국내 원거리)
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "regionPathStandard",
            "ruleId": None,
            "targetStepId": "p4Collect",  # STANDARD 프로토콜 (수도권)
            "priority": 0,
            "isDefault": True,
        },
    ],

    # === Persona 5 (revisionFatigue): 유방암 + 보형물 분기 ===
    # p5AskMedical에서 유방암/보형물 조건 기반 분기 (p5AskDetail에서 분리됨)
    "p5AskMedical": [
        {
            "transitionId": "transCancerCheck",
            "ruleId": "ruleCancerNone",
            "targetStepId": "p5InformSurgery",  # STANDARD
            "priority": 30,
            "isDefault": False,
        },
        {
            "transitionId": "transCancerCheck",
            "ruleId": "ruleCancerConditional",
            "targetStepId": "p5InformSurgery",  # CONDITIONAL
            "priority": 20,
            "isDefault": False,
        },
        {
            "transitionId": "transCancerCheck",
            "ruleId": "ruleCancerNotAllowed",
            "targetStepId": "p5InformSurgery",  # NOT_ALLOWED
            "priority": 10,
            "isDefault": False,
        },
        {
            "transitionId": "transCancerDefault",
            "ruleId": None,
            "targetStepId": "p5InformSurgery",  # Default: 조건 미충족 시 STANDARD로 진행
            "priority": 0,
            "isDefault": True,
        },
    ],
}
