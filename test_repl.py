"""
test_repl.py - 테스트 시나리오 기반 시뮬레이션 REPL

테스트 시나리오 데이터를 사용자 발화로 변환하여
실제 챗봇 process_turn()을 턴 단위로 실행하고 로그를 트래킹.

사용법:
  python test_repl.py --db local                     # 대화형: 시나리오 선택 후 자동 실행
  python test_repl.py --db local --scenario p1std     # 특정 시나리오 자동 실행
  python test_repl.py --db local --scenario all       # 전체 시나리오 순차 실행
  python test_repl.py --db local --interactive        # 수동 입력 + 로그 트래킹
  python test_repl.py --db local --step               # 턴마다 일시정지 (Enter로 진행)
  python test_repl.py --db local -s p1std --with-llm --model gpt-4o  # gpt-4o로 실행
  python test_repl.py --db local -s p1std --with-llm --model gpt-5   # gpt-5로 실행

옵션:
  --no-llm    LLM 호출 없이 flow 로직만 테스트 (slot을 직접 주입)
  --with-llm  실제 LLM으로 slot 추출 및 응답 생성
  --model     챗봇 모델 선택: gpt-4o 또는 gpt-5 (기본: .env 설정값)
  --step      턴마다 일시정지
  --verbose   상세 로그 출력
"""

from __future__ import annotations

import argparse
import logging
import sys
import os
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from neo4j import GraphDatabase
from flow import FlowEngine
from state import ConversationState
from schema import (
    BRANCHING_RULES,
    AUTO_COMPUTABLE_SLOTS,
    CONDITIONAL_SKIP_RULES,
    SYSTEM_MANAGED_SLOTS,
)

# =============================================================================
# 색상 유틸리티
# =============================================================================
class C:
    """ANSI 컬러 코드"""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    GRAY   = "\033[90m"

def header(text):
    return f"{C.BOLD}{C.CYAN}{text}{C.RESET}"

def step_label(text):
    return f"{C.BOLD}{C.MAGENTA}{text}{C.RESET}"

def slot_label(k, v):
    return f"{C.YELLOW}{k}{C.RESET}={C.WHITE}{v}{C.RESET}"

def ok(text):
    return f"{C.GREEN}{text}{C.RESET}"

def warn(text):
    return f"{C.YELLOW}{text}{C.RESET}"

def err(text):
    return f"{C.RED}{text}{C.RESET}"

def dim(text):
    return f"{C.DIM}{text}{C.RESET}"


# =============================================================================
# Step별 체크포인트 필수 슬롯 (판단기준 문서 기반 Layer 5)
# 각 Step에서 반드시 수집되어야 하는 슬롯 목록
# AUTO_COMPUTABLE, SYSTEM_MANAGED, conditional skip 대상은 별도 처리
# =============================================================================

STEP_CHECKPOINT_REQUIREMENTS: dict[str, list[str]] = {
    # ── P1 slimBody ──
    # Graph CHECKS 기준으로 정렬. conditional 슬롯은 주석으로 표기.
    "p1CollectInfo": ["bodyInfo", "bodyFat", "bodyType", "inbodyAvailable"],
    "p1AskLifestyle": ["activityPattern", "exerciseLevel", "dietPattern", "weightGainIntent"],
    "p1AskDetail": ["fatSourceAvailability", "pastOps", "pastOpsSite"],
    # p1InformSurgery: inform step (no user input)
    "p1InformInfo": ["recoveryGuideline"],  # nutritionConsult, weightGainPlan are conditional (Graph has them)
    "p1Confirm": ["customerName", "phoneNumber", "surgeryWindow", "recheckSchedule"],

    # ── P2 lipoCustomer ──
    "p2PreCollect": ["basicInfo", "bodyInfo", "schedule", "concernArea", "medicalHistory"],
    "p2Collect": ["travelConstraint"],  # bodyInfo, schedule also in Graph but already collected at p2PreCollect
    "p2AskLifestyle": ["activityPattern", "exerciseLevel", "smoking", "recoveryAllowance", "jobIntensity"],
    "p2AskDetail": ["fatSourceAvailability", "lipoArea", "lipoGoal", "riskFactor", "pastOps"],
    "p2InformSurgery": ["planPreference", "upsellAccept", "concernSideEffect", "costSensitivity"],  # recoveryAllowance also in Graph but already collected
    "p2InformInfoA": ["recoveryTimeline", "lipoPlanDetail", "costRange"],
    "p2InformInfoB": ["transferType", "recoveryTimeline", "graftExpectation", "costRange", "transferPlanDetail"],
    "p2Finalize": ["precheckRequired", "visitSchedule", "sameDayPossible", "reservationIntent"],

    # ── P3 skinTreatment ──
    "p3Collect": ["bodyInfo", "bodyFat", "skinType", "skinCondition"],
    "p3AskLifestyle": ["activityPattern", "sunExposure", "skincareRoutine", "smoking"],
    "p3AskDetail": ["fatSourceAvailability", "allergyHistory", "pastOps", "botoxCycle", "fillerRemaining", "pastOpsSite"],
    "p3AskSurgery": ["concernArea", "desiredEffect", "durabilityExpectation"],
    # p3InformSurgery: inform step (no user input)
    "p3Confirm": ["customerName", "phoneNumber", "surgeryWindow", "visitSchedule", "procedurePlan"],

    # ── P4 longDistance ──
    "p4PreCollect": ["residenceCountry", "visitPeriod", "travelConstraint"],  # domesticDistrict, regionBucket are conditional (Graph has them)
    "p4Collect": ["bodyInfo", "bodyFat", "inbodyAvailable"],  # inbodyPhotoUpload is conditional (Graph has it)
    "p4AskLifestyle": ["activityPattern", "exerciseLevel", "smoking", "recoveryAllowance"],
    "p4AskDetail": ["fatSourceAvailability", "pastOps", "pastOpsSite"],
    # p4InformSurgery: inform step (no user input)
    "p4InformInfo": ["precheckTimeEstimate", "bodyPhotoUpload", "documentUpload"],
    "p4Confirm": ["surgeryWindow", "depositReservation"],
    "p4Finalize": ["customerName", "phoneNumber", "aftercarePlan", "followupSchedule"],

    # ── P5 revisionFatigue ──
    "p5Collect": ["bodyInfo", "bodyFat", "bodyType"],
    "p5AskLifestyle": ["activityPattern", "smoking", "workConstraint", "recoveryAllowance"],
    "p5AskDetail": ["breastCancerHistory", "implantPresence", "cancerSurgeryType",
                     "fatSourceAvailability", "pastOps", "pastOpsSite"],  # Graph에 6개 모두 연결
    "p5AskMedical": ["implantCondition", "implantOriginHospital"],  # Graph 실제: 보형물 상세만 (conditional)
    # p5InformSurgery: inform step (no user input)
    "p5InformInfo": ["aftercarePlan", "scarManagement", "riskExplanationLevel"],
    "p5Confirm": ["customerName", "phoneNumber", "surgeryWindow", "visitSchedule", "procedurePlan"],
}

# =============================================================================
# 테스트 시나리오 데이터 (사용자 발화 시뮬레이션)
# =============================================================================

# 각 시나리오: { step_id: [ (user_utterance, expected_slots) ] }
# user_utterance: 실제 사용자가 말하는 것처럼 자연어로 작성
# expected_slots: 그 발화에서 추출되어야 할 slot들
# initial_utterance: 챗봇 인사("어떤 상담이 필요하신가요?")에 대한 첫 응답 (페르소나 추론용)

TEST_SCENARIOS = {
    # =========================================================================
    # Persona 1: slimBody (scenLowFat)
    # 분기: p1InformSurgery에서 BMI ≥23 → STANDARD / BMI <23 → LOW-FAT
    # 조건부 스킵: weightGainIntent=false → weightGainPlan, nutritionConsult 스킵
    # =========================================================================

    "p1std": {
        "name": "P1 슬림바디 - STANDARD (BMI≥23, 지방 충분 → 가슴 줄기세포 지방이식 가능)",
        "persona": "slimBody",
        "scenario": "scenLowFat",
        "initial_utterance": "안녕하세요, 가슴에 줄기세포 지방이식 하고 싶은데 체지방이 충분한지 상담받고 싶어요.",
        "expected_path": [
            "p1CollectInfo", "p1AskLifestyle", "p1AskDetail",
            "p1InformSurgery", "p1InformInfo", "p1Confirm",
        ],
        "branch_info": "BMI=26.1 → STANDARD, weightGainIntent=false → skip(weightGainPlan, nutritionConsult)",
        "turns": [
            {"step": "p1CollectInfo", "utterance": "키 165cm이고 몸무게 71kg이에요. 체지방률은 30%정도 되고, 보통 체형이에요. 인바디는 있어요.",
             "slots": {"bodyInfo": "165cm 71kg", "bodyFat": "30", "bodyType": "보통", "inbodyAvailable": "true"}},
            {"step": "p1AskLifestyle", "utterance": "주 3회 운동하고 있어요. 운동 강도는 중간이고 식단은 불규칙해요. 체중 증량은 필요 없어요.",
             "slots": {"activityPattern": "주3회 운동", "exerciseLevel": "중간", "dietPattern": "불규칙", "weightGainIntent": "false"}},
            {"step": "p1AskDetail", "utterance": "복부랑 허벅지에서 지방 채취 가능하고요, 가슴 관련 시술 이력은 없습니다.",
             "slots": {"fatSourceAvailability": "복부, 허벅지", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p1InformSurgery → BMI 26.1 → ruleBodyFatHigh → STANDARD
            {"step": "p1InformInfo", "utterance": "회복 가이드라인은 2주 압박복 착용으로 할게요.",
             "slots": {"recoveryGuideline": "2주 압박복 착용"}},
            {"step": "p1Confirm", "utterance": "김지현입니다. 010-9876-5432에요. 다음달에 수술 가능하고, 재확인은 2주 후에 할게요.",
             "slots": {"customerName": "김지현", "phoneNumber": "010-9876-5432", "surgeryWindow": "다음달", "recheckSchedule": "2주 후"}},
        ],
    },

    "p1lf": {
        "name": "P1 슬림바디 - LOW-FAT (BMI<23, 가슴 지방이식 위해 증량 희망)",
        "persona": "slimBody",
        "scenario": "scenLowFat",
        "initial_utterance": "마른 체형인데 가슴에 지방이식 하고 싶어요. 채취할 지방이 충분할지 걱정이에요.",
        "expected_path": [
            "p1CollectInfo", "p1AskLifestyle", "p1AskDetail",
            "p1InformSurgery", "p1InformInfo", "p1Confirm",
        ],
        "branch_info": "BMI=20.2 → LOW-FAT, weightGainIntent=true → collect(weightGainPlan, nutritionConsult)",
        "turns": [
            {"step": "p1CollectInfo", "utterance": "165cm에 55kg이에요. 체지방 18%이고 마른체형입니다. 인바디는 없어요.",
             "slots": {"bodyInfo": "165cm 55kg", "bodyFat": "18", "bodyType": "마른체형", "inbodyAvailable": "false"}},
            {"step": "p1AskLifestyle", "utterance": "운동은 거의 안 해요. 소식하는 편이고 가슴 지방이식을 위해 체중 좀 늘리고 싶어요.",
             "slots": {"activityPattern": "거의 안함", "exerciseLevel": "낮음", "dietPattern": "소식", "weightGainIntent": "true"}},
            {"step": "p1AskDetail", "utterance": "허벅지에 지방이 소량 있고, 가슴 시술 경험은 없습니다.",
             "slots": {"fatSourceAvailability": "허벅지 소량", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p1InformSurgery → BMI 20.2 → ruleBodyFatLow → LOW-FAT
            {"step": "p1InformInfo", "utterance": "한달에 3kg 증량 목표로 하고, 영양사 상담도 받고 싶어요. 회복은 3주 압박복이요.",
             "slots": {"weightGainPlan": "한달 3kg 증량 목표", "nutritionConsult": "영양사 상담 희망", "recoveryGuideline": "3주 압박복"}},
            {"step": "p1Confirm", "utterance": "이수진이에요. 010-1111-2222입니다. 2개월 후에 수술하고 1개월 후에 재방문할게요.",
             "slots": {"customerName": "이수진", "phoneNumber": "010-1111-2222", "surgeryWindow": "2개월 후", "recheckSchedule": "1개월 후"}},
        ],
    },

    "p1lf_nogain": {
        "name": "P1 슬림바디 - LOW-FAT (BMI<23, 가슴 지방이식 희망하나 증량 거부)",
        "persona": "slimBody",
        "scenario": "scenLowFat",
        "initial_utterance": "가슴에 줄기세포 지방이식 받고 싶은데요, 마른편이라 지방이 부족할 수도 있다고 하더라고요.",
        "expected_path": [
            "p1CollectInfo", "p1AskLifestyle", "p1AskDetail",
            "p1InformSurgery", "p1InformInfo", "p1Confirm",
        ],
        "branch_info": "BMI=19.7 → LOW-FAT, weightGainIntent=false → skip(weightGainPlan, nutritionConsult)",
        "turns": [
            {"step": "p1CollectInfo", "utterance": "158cm 49kg이에요. 체지방 17%이고 마른편이에요. 인바디 있어요.",
             "slots": {"bodyInfo": "158cm 49kg", "bodyFat": "17", "bodyType": "마른편", "inbodyAvailable": "true"}},
            {"step": "p1AskLifestyle", "utterance": "필라테스 주2회 해요. 식단은 규칙적이고 체중 증량은 안 할 거예요.",
             "slots": {"activityPattern": "필라테스 주2회", "exerciseLevel": "낮음", "dietPattern": "규칙적", "weightGainIntent": "false"}},
            {"step": "p1AskDetail", "utterance": "허벅지 안쪽에 지방 소량이요. 가슴 시술은 처음입니다.",
             "slots": {"fatSourceAvailability": "허벅지 안쪽 소량", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p1InformSurgery → BMI 19.7 → ruleBodyFatLow → LOW-FAT
            # p1InformInfo: weightGainPlan, nutritionConsult 스킵됨
            {"step": "p1InformInfo", "utterance": "회복은 2주 압박복으로 하겠습니다.",
             "slots": {"recoveryGuideline": "2주 압박복"}},
            {"step": "p1Confirm", "utterance": "박서연이에요. 연락처는 010-3333-4444예요. 3주 후에 수술하고 2주 후 재확인할게요.",
             "slots": {"customerName": "박서연", "phoneNumber": "010-3333-4444", "surgeryWindow": "3주 후", "recheckSchedule": "2주 후"}},
        ],
    },

    # =========================================================================
    # Persona 2: lipoCustomer (scenLipoGraft)
    # 분기1: p2InformSurgery에서 upsellAccept=false → p2InformInfoA / true → p2InformInfoB
    # 분기2: p2InformInfoB에서 transferType=일반/줄기세포 → p2Finalize
    # =========================================================================

    "p2a": {
        "name": "P2 지방흡입 - 흡입 단독, 가슴이식 미선택 (upsellAccept=false)",
        "persona": "lipoCustomer",
        "scenario": "scenLipoGraft",
        "initial_utterance": "지방흡입 상담 받으려고요. 복부 지방흡입 후 가슴 이식도 가능한지 알아보고 있어요.",
        "expected_path": [
            "p2PreCollect", "p2Collect", "p2AskLifestyle", "p2AskDetail",
            "p2InformSurgery", "p2InformInfoA", "p2Finalize",
        ],
        "branch_info": "upsellAccept=false → p2InformInfoA (흡입 단독)",
        "turns": [
            {"step": "p2PreCollect", "utterance": "163cm 62kg이고 다음주 화요일에 상담 가능해요. 가슴 볼륨이 고민이고 병력은 없습니다. 서지영 010-1234-5678입니다.",
             "slots": {"bodyInfo": "163cm 62kg", "schedule": "다음주 화요일", "concernArea": "가슴 볼륨", "medicalHistory": "없음", "basicInfo": "서지영 010-1234-5678"}},
            {"step": "p2Collect", "utterance": "교통편 제약은 없어요.",
             "slots": {"travelConstraint": "없음"}},
            {"step": "p2AskLifestyle", "utterance": "주3회 필라테스하고 운동 강도 중간이에요. 비흡연이고 회복 기간 2주 가능해요. 사무직입니다.",
             "slots": {"activityPattern": "주3회 필라테스", "exerciseLevel": "중간", "smoking": "false", "recoveryAllowance": "2주", "jobIntensity": "사무직"}},
            {"step": "p2AskDetail", "utterance": "복부에 지방 충분하고 복부 옆구리 흡입 원해요. 가슴 볼륨 업이 목표고 위험요소 없어요. 과거 시술 없습니다.",
             "slots": {"fatSourceAvailability": "복부 충분", "lipoArea": "복부, 옆구리", "lipoGoal": "가슴 볼륨 업", "riskFactor": "없음", "pastOps": "없음"}},
            {"step": "p2InformSurgery", "utterance": "일단 흡입 단독으로 하고 싶어요. 가슴 이식은 나중에 고려할게요. 멍이 좀 걱정되고 비용은 중간 정도면 좋겠어요.",
             "slots": {"planPreference": "흡입 단독", "upsellAccept": "false", "concernSideEffect": "멍", "costSensitivity": "중간", "recoveryAllowance": "2주"}},
            {"step": "p2InformInfoA", "utterance": "회복은 2주 압박복, 복부 전체 흡입으로 진행하고 비용은 300-500만원 사이면 좋겠어요.",
             "slots": {"recoveryTimeline": "2주 압박복", "lipoPlanDetail": "복부 전체 흡입", "costRange": "300-500만원"}},
            {"step": "p2Finalize", "utterance": "사전검사 필요하고 다음주 목요일에 방문할게요. 당일 수술은 안 되고 예약 의사 있습니다.",
             "slots": {"precheckRequired": "true", "visitSchedule": "다음주 목요일", "sameDayPossible": "false", "reservationIntent": "true"}},
        ],
    },

    "p2b_stem": {
        "name": "P2 지방흡입 - 흡입+가슴이식, 줄기세포 (upsellAccept=true, transferType=줄기세포)",
        "persona": "lipoCustomer",
        "scenario": "scenLipoGraft",
        "initial_utterance": "지방흡입이랑 가슴에 줄기세포 지방이식을 같이 하고 싶어서요.",
        "expected_path": [
            "p2PreCollect", "p2Collect", "p2AskLifestyle", "p2AskDetail",
            "p2InformSurgery", "p2InformInfoB", "p2Finalize",
        ],
        "branch_info": "upsellAccept=true → p2InformInfoB, transferType=줄기세포 → p2Finalize",
        "turns": [
            {"step": "p2PreCollect", "utterance": "168cm 65kg입니다. 이번주 금요일 가능하고 가슴 볼륨이 고민이에요. 병력 없고 이영희 010-5678-1234예요.",
             "slots": {"bodyInfo": "168cm 65kg", "schedule": "이번주 금요일", "concernArea": "가슴 볼륨", "medicalHistory": "없음", "basicInfo": "이영희 010-5678-1234"}},
            {"step": "p2Collect", "utterance": "이동 제약 없습니다.",
             "slots": {"travelConstraint": "없음"}},
            {"step": "p2AskLifestyle", "utterance": "주 2회 운동하고 중간 강도예요. 담배 안 피우고 3주 회복 가능합니다. 프리랜서에요.",
             "slots": {"activityPattern": "주2회", "exerciseLevel": "중간", "smoking": "false", "recoveryAllowance": "3주", "jobIntensity": "프리랜서"}},
            {"step": "p2AskDetail", "utterance": "허벅지에서 지방 채취하고 허벅지 안쪽 흡입 원해요. 가슴 이식용 지방 확보가 목적이고 위험요소 없어요. 과거 시술 없음.",
             "slots": {"fatSourceAvailability": "허벅지", "lipoArea": "허벅지 안쪽", "lipoGoal": "가슴 이식용 지방 확보", "riskFactor": "없음", "pastOps": "없음"}},
            {"step": "p2InformSurgery", "utterance": "흡입이랑 가슴 이식 같이 하고 싶어요. 부기가 걱정되고 비용은 좀 높아도 괜찮아요.",
             "slots": {"planPreference": "흡입+가슴이식", "upsellAccept": "true", "concernSideEffect": "부기", "costSensitivity": "낮음", "recoveryAllowance": "3주"}},
            {"step": "p2InformInfoB", "utterance": "줄기세포 이식으로 하고 싶어요. 줄기세포 이식으로 가슴 볼륨 보충 계획이에요. 회복 4주 예상하고 자연스러운 가슴 볼륨 원해요. 800-1200만원 예산이에요.",
             "slots": {"transferType": "줄기세포", "transferPlanDetail": "줄기세포 이식 가슴 볼륨 보충", "recoveryTimeline": "4주 회복", "graftExpectation": "자연스러운 가슴 볼륨", "costRange": "800-1200만원"}},
            {"step": "p2Finalize", "utterance": "사전검사 하고 다음주 월요일에 방문합니다. 당일 수술도 가능하면 좋겠고 예약할게요.",
             "slots": {"precheckRequired": "true", "visitSchedule": "다음주 월요일", "sameDayPossible": "true", "reservationIntent": "true"}},
        ],
    },

    "p2b_general": {
        "name": "P2 지방흡입 - 흡입+가슴이식, 일반 (upsellAccept=true, transferType=일반)",
        "persona": "lipoCustomer",
        "scenario": "scenLipoGraft",
        "initial_utterance": "복부 지방흡입하고 가슴에 일반 지방이식도 같이 하고 싶어요.",
        "expected_path": [
            "p2PreCollect", "p2Collect", "p2AskLifestyle", "p2AskDetail",
            "p2InformSurgery", "p2InformInfoB", "p2Finalize",
        ],
        "branch_info": "upsellAccept=true → p2InformInfoB, transferType=일반 → p2Finalize",
        "turns": [
            {"step": "p2PreCollect", "utterance": "160cm 58kg이에요. 이번주 토요일 가능하고 가슴 볼륨이 고민입니다. 병력 없고 한소희 010-2222-3333이에요.",
             "slots": {"bodyInfo": "160cm 58kg", "schedule": "이번주 토요일", "concernArea": "가슴 볼륨", "medicalHistory": "없음", "basicInfo": "한소희 010-2222-3333"}},
            {"step": "p2Collect", "utterance": "교통편 문제없어요.",
             "slots": {"travelConstraint": "없음"}},
            {"step": "p2AskLifestyle", "utterance": "주4회 수영하고 강도 중간이에요. 비흡연이고 2주 회복 가능합니다. 교사에요.",
             "slots": {"activityPattern": "주4회 수영", "exerciseLevel": "중간", "smoking": "false", "recoveryAllowance": "2주", "jobIntensity": "교사"}},
            {"step": "p2AskDetail", "utterance": "복부에 지방 넉넉하고 복부 흡입 원합니다. 가슴 볼륨 업이 목표고 특별한 위험요소 없어요. 시술 이력 없음.",
             "slots": {"fatSourceAvailability": "복부 넉넉", "lipoArea": "복부", "lipoGoal": "가슴 볼륨 업", "riskFactor": "없음", "pastOps": "없음"}},
            {"step": "p2InformSurgery", "utterance": "가슴 이식도 함께 하고 싶어요. 비용은 적당하면 좋겠고 붓기가 걱정이에요.",
             "slots": {"planPreference": "흡입+가슴이식", "upsellAccept": "true", "concernSideEffect": "붓기", "costSensitivity": "중간", "recoveryAllowance": "2주"}},
            {"step": "p2InformInfoB", "utterance": "일반 이식으로 할게요. 일반 이식으로 가슴 볼륨 보충할 계획이에요. 회복 2주 예상하고 자연스러운 가슴 결과 원해요. 500-700만원 예산입니다.",
             "slots": {"transferType": "일반", "transferPlanDetail": "일반 이식 가슴 볼륨 보충", "recoveryTimeline": "2주 회복", "graftExpectation": "자연스러운 가슴 결과", "costRange": "500-700만원"}},
            {"step": "p2Finalize", "utterance": "사전검사 하고 다음주 수요일 방문합니다. 당일 수술은 안 되고 예약할게요.",
             "slots": {"precheckRequired": "true", "visitSchedule": "다음주 수요일", "sameDayPossible": "false", "reservationIntent": "true"}},
        ],
    },

    # =========================================================================
    # Persona 3: skinTreatment (scenAntiAging)
    # 분기: 없음 (선형 플로우)
    # =========================================================================

    "p3": {
        "name": "P3 피부시술 - 가슴성형 전후 피부관리 + 줄기세포 안티에이징 (선형)",
        "persona": "skinTreatment",
        "scenario": "scenAntiAging",
        "initial_utterance": "가슴 줄기세포 지방이식을 고려하고 있는데, 수술 전후 가슴 피부 탄력이랑 흉터 관리도 같이 상담받고 싶어요.",
        "expected_path": [
            "p3Collect", "p3AskLifestyle", "p3AskDetail",
            "p3AskSurgery", "p3InformSugery", "p3Confirm",
        ],
        "branch_info": "분기 없음 (선형)",
        "turns": [
            {"step": "p3Collect", "utterance": "162cm 50kg이고 체지방 22%예요. 건성 피부에 가슴 부위 탄력 저하가 고민이에요.",
             "slots": {"bodyInfo": "162cm 50kg", "bodyFat": "22", "skinType": "건성", "skinCondition": "가슴 부위 탄력 저하, 흉터 우려"}},
            {"step": "p3AskLifestyle", "utterance": "요가 주2회 하고요. 야외 근무라 자외선 노출이 많아요. 기초 화장품만 쓰고 담배는 안 펴요.",
             "slots": {"activityPattern": "요가 주2회", "sunExposure": "높음", "skincareRoutine": "기초 화장품만 사용", "smoking": "false"}},
            {"step": "p3AskDetail", "utterance": "허벅지 지방 있고 필러 잔여물 없어요. 알레르기 없고 가슴 관련 보톡스 경험은 없어요. 과거 시술 없고 보톡스 주기도 없습니다.",
             "slots": {"fatSourceAvailability": "허벅지", "fillerRemaining": "false", "allergyHistory": "없음", "pastOps": "없음", "pastOpsSite": "없음", "botoxCycle": "없음"}},
            {"step": "p3AskSurgery", "utterance": "가슴 지방이식 후 피부 탄력 개선이 고민이에요. 자연스러운 가슴 라인과 피부결 효과 원하고 1년 이상 지속되면 좋겠어요.",
             "slots": {"concernArea": "가슴 피부 탄력, 수술 후 흉터", "desiredEffect": "자연스러운 가슴 라인 + 피부결 개선", "durabilityExpectation": "1년 이상"}},
            # p3InformSugery: no checks
            {"step": "p3Confirm", "utterance": "최윤아예요. 010-4444-5555입니다. 이번달 내에 하고 싶고 다음주 수요일 방문 가능해요. 줄기세포 지방이식 + 피부 탄력 시술 계획이에요.",
             "slots": {"customerName": "최윤아", "phoneNumber": "010-4444-5555", "surgeryWindow": "이번달 내", "visitSchedule": "다음주 수요일", "procedurePlan": "줄기세포 지방이식 + 피부 탄력 시술"}},
        ],
    },

    # =========================================================================
    # Persona 4: longDistance (scenRemote)
    # 분기: p4PreCollect에서 regionBucket 기반
    #   ABROAD → FULL / 국내원거리(S3~S6) → SEMI-REMOTE / 수도권(S1~S2) → STANDARD
    # 조건부 스킵: residenceCountry=ABROAD → domesticDistrict 스킵
    #             inbodyAvailable=false → inbodyPhotoUpload 스킵
    # =========================================================================

    "p4abroad": {
        "name": "P4 원거리 - 해외 (FULL 프로토콜, 가슴 줄기세포 지방이식)",
        "persona": "longDistance",
        "scenario": "scenRemote",
        "initial_utterance": "해외에 살고 있는데 한국에서 가슴 줄기세포 지방이식 받으려고요. 원거리 상담 가능할까요?",
        "expected_path": [
            "p4PreCollect", "p4Collect", "p4AskLifestyle", "p4AskDetail",
            "p4InformSurgery", "p4InformInfo", "p4Confirm", "p4Finalize",
        ],
        "branch_info": "residenceCountry=ABROAD → regionBucket=ABROAD → FULL, domesticDistrict 스킵, inbodyAvailable=false → inbodyPhotoUpload 스킵",
        "turns": [
            {"step": "p4PreCollect", "utterance": "해외에 살고 있어요. 2주 정도 한국 방문 가능하고 비자가 필요해요.",
             "slots": {"residenceCountry": "ABROAD", "visitPeriod": "2주", "travelConstraint": "비자 필요"}},
            {"step": "p4Collect", "utterance": "163cm 55kg이고 체지방 24%예요. 인바디 데이터는 없어요.",
             "slots": {"bodyInfo": "163cm 55kg", "bodyFat": "24", "inbodyAvailable": "false"}},
            {"step": "p4AskLifestyle", "utterance": "주 3회 요가하고 중간 강도예요. 담배 안 피고 3주 회복 가능합니다.",
             "slots": {"activityPattern": "주3회 요가", "exerciseLevel": "중간", "smoking": "false", "recoveryAllowance": "3주"}},
            {"step": "p4AskDetail", "utterance": "복부에서 지방 채취 가능하고 가슴 관련 시술 이력 없어요.",
             "slots": {"fatSourceAvailability": "복부", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p4InformSurgery: no checks
            {"step": "p4InformInfo", "utterance": "사전검사 2시간 예상하고 체형 사진이랑 서류 업로드했어요.",
             "slots": {"precheckTimeEstimate": "2시간", "bodyPhotoUpload": "uploaded", "documentUpload": "uploaded"}},
            {"step": "p4Confirm", "utterance": "다음달에 수술하고 보증금 예약할게요.",
             "slots": {"surgeryWindow": "다음달", "depositReservation": "true"}},
            {"step": "p4Finalize", "utterance": "정하나에요. 010-6666-7777입니다. 현지 병원 연계로 사후관리하고 수술 후 2주 원격 상담 받을게요.",
             "slots": {"customerName": "정하나", "phoneNumber": "010-6666-7777", "aftercarePlan": "현지 병원 연계", "followupSchedule": "수술 후 2주 원격 상담"}},
        ],
    },

    "p4semi": {
        "name": "P4 원거리 - 부산 (SEMI-REMOTE 프로토콜, 가슴 지방이식)",
        "persona": "longDistance",
        "scenario": "scenRemote",
        "initial_utterance": "부산에서 서울까지 가야 하는데 가슴 줄기세포 지방이식 원거리 상담 가능할까요?",
        "expected_path": [
            "p4PreCollect", "p4Collect", "p4AskLifestyle", "p4AskDetail",
            "p4InformSurgery", "p4InformInfo", "p4Confirm", "p4Finalize",
        ],
        "branch_info": "residenceCountry=한국, domesticDistrict=부산 → regionBucket=S4 → SEMI-REMOTE",
        "turns": [
            {"step": "p4PreCollect", "utterance": "한국 부산에 살고 있어요. 3일 정도 서울 방문 가능하고 KTX 이용합니다.",
             "slots": {"residenceCountry": "한국", "domesticDistrict": "부산", "visitPeriod": "3일", "travelConstraint": "KTX 이용"}},
            {"step": "p4Collect", "utterance": "162cm 56kg이고 체지방 25%예요. 인바디 있고 사진도 업로드했어요.",
             "slots": {"bodyInfo": "162cm 56kg", "bodyFat": "25", "inbodyAvailable": "true", "inbodyPhotoUpload": "uploaded"}},
            {"step": "p4AskLifestyle", "utterance": "주3회 필라테스 다니고 중간 강도예요. 비흡연이고 2주 회복 가능합니다.",
             "slots": {"activityPattern": "주3회 필라테스", "exerciseLevel": "중간", "smoking": "false", "recoveryAllowance": "2주"}},
            {"step": "p4AskDetail", "utterance": "복부 허벅지에서 채취 가능. 가슴 시술 이력 없습니다.",
             "slots": {"fatSourceAvailability": "복부, 허벅지", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p4InformSurgery: no checks
            {"step": "p4InformInfo", "utterance": "사전검사 1시간이면 되고 사진 서류 다 올렸어요.",
             "slots": {"precheckTimeEstimate": "1시간", "bodyPhotoUpload": "uploaded", "documentUpload": "uploaded"}},
            {"step": "p4Confirm", "utterance": "이번달에 수술하고 보증금 입금합니다.",
             "slots": {"surgeryWindow": "이번달", "depositReservation": "true"}},
            {"step": "p4Finalize", "utterance": "윤다혜예요. 010-8888-9999입니다. 지역 병원 연계 사후관리하고 1주 후 재방문할게요.",
             "slots": {"customerName": "윤다혜", "phoneNumber": "010-8888-9999", "aftercarePlan": "지역 병원 연계", "followupSchedule": "1주 후 재방문"}},
        ],
    },

    "p4std": {
        "name": "P4 원거리 - 서울 (STANDARD 프로토콜, 가슴 지방이식)",
        "persona": "longDistance",
        "scenario": "scenRemote",
        "initial_utterance": "서울 사는데 가슴 줄기세포 지방이식 상담 받으려고요. 내원 상담이 가능한지 궁금해요.",
        "expected_path": [
            "p4PreCollect", "p4Collect", "p4AskLifestyle", "p4AskDetail",
            "p4InformSurgery", "p4InformInfo", "p4Confirm", "p4Finalize",
        ],
        "branch_info": "residenceCountry=한국, domesticDistrict=서울 → regionBucket=S1 → STANDARD (default)",
        "turns": [
            {"step": "p4PreCollect", "utterance": "서울에 살고 있어요. 수시로 방문 가능하고 교통 제약 없습니다.",
             "slots": {"residenceCountry": "한국", "domesticDistrict": "서울", "visitPeriod": "수시 가능", "travelConstraint": "없음"}},
            {"step": "p4Collect", "utterance": "160cm 52kg이고 체지방 23%예요. 인바디 있고 사진 업로드했어요.",
             "slots": {"bodyInfo": "160cm 52kg", "bodyFat": "23", "inbodyAvailable": "true", "inbodyPhotoUpload": "uploaded"}},
            {"step": "p4AskLifestyle", "utterance": "주3회 러닝하고 중간 강도예요. 비흡연이고 2주 회복 가능합니다.",
             "slots": {"activityPattern": "주3회 러닝", "exerciseLevel": "중간", "smoking": "false", "recoveryAllowance": "2주"}},
            {"step": "p4AskDetail", "utterance": "복부 지방 충분하고 가슴 관련 시술 이력 없어요.",
             "slots": {"fatSourceAvailability": "복부 충분", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p4InformSurgery: no checks
            {"step": "p4InformInfo", "utterance": "사전검사 30분이면 되고 사진 서류 준비됐어요.",
             "slots": {"precheckTimeEstimate": "30분", "bodyPhotoUpload": "uploaded", "documentUpload": "uploaded"}},
            {"step": "p4Confirm", "utterance": "이번주에 수술하고 보증금 납부하겠습니다.",
             "slots": {"surgeryWindow": "이번주", "depositReservation": "true"}},
            {"step": "p4Finalize", "utterance": "윤서아예요. 010-5555-6666입니다. 직접 내원 사후관리하고 1주 후 내원할게요.",
             "slots": {"customerName": "윤서아", "phoneNumber": "010-5555-6666", "aftercarePlan": "직접 내원", "followupSchedule": "1주 후 내원"}},
        ],
    },

    # =========================================================================
    # Persona 5: revisionFatigue (scenRevision)
    # 분기: p5AskMedical에서 유방암/보형물 조건 기반
    #   breastCancerHistory=false → STANDARD
    #   breastCancerHistory=true + cancerSurgeryType=부분 → CONDITIONAL
    #   breastCancerHistory=true + cancerSurgeryType=완전 → NOT_ALLOWED
    # 조건부 스킵: implantPresence=false → implantCondition, implantOriginHospital 스킵
    # =========================================================================

    "p5_std": {
        "name": "P5 재수술 - STANDARD (유방암 없음, 보형물 없음)",
        "persona": "revisionFatigue",
        "scenario": "scenRevision",
        "initial_utterance": "이전에 했던 시술 결과가 불만족스러워서 재수술 상담 받고 싶어요.",
        "expected_path": [
            "p5Collect", "p5AskLifestyle", "p5AskDetail",
            "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
        ],
        "branch_info": "breastCancerHistory=false → STANDARD, implantPresence=false → skip(implantCondition, implantOriginHospital)",
        "turns": [
            {"step": "p5Collect", "utterance": "160cm 55kg이고 체지방 24%예요. 보통 체형이에요.",
             "slots": {"bodyInfo": "160cm 55kg", "bodyFat": "24", "bodyType": "보통"}},
            {"step": "p5AskLifestyle", "utterance": "가끔 산책하고 비흡연이에요. 사무직이고 2주 회복 가능해요.",
             "slots": {"activityPattern": "가끔 산책", "smoking": "false", "workConstraint": "사무직", "recoveryAllowance": "2주"}},
            # Graph: p5AskDetail CHECKS [breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite]
            {"step": "p5AskDetail", "utterance": "유방암 이력 없어요. 보형물도 없습니다. 암 수술은 해당없어요. 복부 지방 있고 가슴 확대 1회 했었어요. 가슴 부위였어요.",
             "slots": {"breastCancerHistory": "false", "implantPresence": "false", "cancerSurgeryType": "해당없음",
                       "fatSourceAvailability": "복부", "pastOps": "가슴 확대 1회", "pastOpsSite": "가슴"}},
            # Graph: p5AskMedical CHECKS [implantCondition, implantOriginHospital] — skipped (implantPresence=false)
            {"step": "p5AskMedical", "utterance": "보형물 관련은 해당없습니다.",
             "slots": {}},
            # p5InformSurgery: ruleCancerNone → STANDARD
            {"step": "p5InformInfo", "utterance": "정기 검진으로 사후관리하고 실리콘 시트로 흉터 관리할게요. 위험성 상세히 설명해주세요.",
             "slots": {"aftercarePlan": "정기 검진", "scarManagement": "실리콘 시트", "riskExplanationLevel": "상세"}},
            {"step": "p5Confirm", "utterance": "강미래에요. 010-7777-8888입니다. 다음달 수술하고 다음주 금요일에 방문할게요. 자가조직 재건으로 계획합니다.",
             "slots": {"customerName": "강미래", "phoneNumber": "010-7777-8888", "surgeryWindow": "다음달", "visitSchedule": "다음주 금요일", "procedurePlan": "자가조직 재건"}},
        ],
    },

    "p5_std_implant": {
        "name": "P5 재수술 - STANDARD (유방암 없음, 보형물 있음)",
        "persona": "revisionFatigue",
        "scenario": "scenRevision",
        "initial_utterance": "보형물 넣었는데 구축이 와서 재수술 알아보고 있어요.",
        "expected_path": [
            "p5Collect", "p5AskLifestyle", "p5AskDetail",
            "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
        ],
        "branch_info": "breastCancerHistory=false → STANDARD, implantPresence=true → collect(implantCondition, implantOriginHospital)",
        "turns": [
            {"step": "p5Collect", "utterance": "163cm 58kg이고 체지방 26%예요. 보통 체형입니다.",
             "slots": {"bodyInfo": "163cm 58kg", "bodyFat": "26", "bodyType": "보통"}},
            {"step": "p5AskLifestyle", "utterance": "주2회 걷기 운동하고 비흡연이에요. 재택근무라 제약 없고 3주 회복 가능해요.",
             "slots": {"activityPattern": "주2회 걷기", "smoking": "false", "workConstraint": "재택근무", "recoveryAllowance": "3주"}},
            # Graph: p5AskDetail CHECKS [breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite]
            {"step": "p5AskDetail", "utterance": "유방암 이력 없어요. 보형물 있습니다. 암 수술은 해당없어요. 복부 지방 있고 가슴 확대 2회 했었어요. 가슴 부위에요.",
             "slots": {"breastCancerHistory": "false", "implantPresence": "true", "cancerSurgeryType": "해당없음",
                       "fatSourceAvailability": "복부", "pastOps": "가슴 확대 2회", "pastOpsSite": "가슴"}},
            # Graph: p5AskMedical CHECKS [implantCondition, implantOriginHospital] — collected (implantPresence=true)
            {"step": "p5AskMedical", "utterance": "보형물 상태는 구축이 왔어요. 이전에 A성형외과에서 했습니다.",
             "slots": {"implantCondition": "구축", "implantOriginHospital": "A성형외과"}},
            # p5InformSurgery: ruleCancerNone → STANDARD
            {"step": "p5InformInfo", "utterance": "월 1회 검진으로 사후관리하고 압박밴드로 흉터 관리할게요. 위험성 기본 설명이면 돼요.",
             "slots": {"aftercarePlan": "월 1회 검진", "scarManagement": "압박밴드", "riskExplanationLevel": "기본"}},
            {"step": "p5Confirm", "utterance": "노은지에요. 010-1212-3434입니다. 2개월 후 수술하고 다음주 화요일 방문할게요. 보형물 교체로 진행합니다.",
             "slots": {"customerName": "노은지", "phoneNumber": "010-1212-3434", "surgeryWindow": "2개월 후", "visitSchedule": "다음주 화요일", "procedurePlan": "보형물 교체"}},
        ],
    },

    "p5_conditional": {
        "name": "P5 재수술 - CONDITIONAL (유방암+부분절제, 보형물 없음)",
        "persona": "revisionFatigue",
        "scenario": "scenRevision",
        "initial_utterance": "유방암 수술 후에 재건 상담을 받고 싶어서요. 부분절제를 했었어요.",
        "expected_path": [
            "p5Collect", "p5AskLifestyle", "p5AskDetail",
            "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
        ],
        "branch_info": "breastCancerHistory=true + cancerSurgeryType=부분 → CONDITIONAL, implantPresence=false → skip",
        "turns": [
            {"step": "p5Collect", "utterance": "155cm 52kg이고 체지방 22%예요. 마른편이에요.",
             "slots": {"bodyInfo": "155cm 52kg", "bodyFat": "22", "bodyType": "마른편"}},
            {"step": "p5AskLifestyle", "utterance": "산책 위주로 운동하고 비흡연이에요. 사무직이고 4주 회복 가능합니다.",
             "slots": {"activityPattern": "산책 위주", "smoking": "false", "workConstraint": "사무직", "recoveryAllowance": "4주"}},
            # Graph: p5AskDetail CHECKS [breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite]
            {"step": "p5AskDetail", "utterance": "유방암 이력이 있어요. 부분절제 수술 받았습니다. 보형물은 없어요. 허벅지 지방 있고 유방 재건 1회 했었어요. 가슴 부위입니다.",
             "slots": {"breastCancerHistory": "true", "implantPresence": "false", "cancerSurgeryType": "부분",
                       "fatSourceAvailability": "허벅지", "pastOps": "유방 재건 1회", "pastOpsSite": "가슴"}},
            # Graph: p5AskMedical CHECKS [implantCondition, implantOriginHospital] — skipped (implantPresence=false)
            {"step": "p5AskMedical", "utterance": "보형물 관련은 해당없어요.",
             "slots": {}},
            # p5InformSurgery: ruleCancerConditional → CONDITIONAL
            {"step": "p5InformInfo", "utterance": "주치의 협진으로 사후관리하고 실리콘 시트 사용할게요. 위험성 상세히 알고 싶어요.",
             "slots": {"aftercarePlan": "주치의 협진", "scarManagement": "실리콘 시트", "riskExplanationLevel": "상세"}},
            {"step": "p5Confirm", "utterance": "오수연이에요. 010-5656-7878입니다. 3개월 후 수술 예정이고 다음주 목요일에 방문할게요. 자가조직 재건으로요.",
             "slots": {"customerName": "오수연", "phoneNumber": "010-5656-7878", "surgeryWindow": "3개월 후", "visitSchedule": "다음주 목요일", "procedurePlan": "자가조직 재건"}},
        ],
    },

    "p5_not_allowed": {
        "name": "P5 재수술 - NOT_ALLOWED (유방암+전절제, 보형물 있음)",
        "persona": "revisionFatigue",
        "scenario": "scenRevision",
        "initial_utterance": "유방암으로 전절제 수술을 받았는데 가슴 재건이 가능한지 상담받고 싶어요.",
        "expected_path": [
            "p5Collect", "p5AskLifestyle", "p5AskDetail",
            "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
        ],
        "branch_info": "breastCancerHistory=true + cancerSurgeryType=완전 → NOT_ALLOWED, implantPresence=true → collect all",
        "turns": [
            {"step": "p5Collect", "utterance": "157cm 50kg이고 체지방 20%예요. 마른편이에요.",
             "slots": {"bodyInfo": "157cm 50kg", "bodyFat": "20", "bodyType": "마른편"}},
            {"step": "p5AskLifestyle", "utterance": "운동은 거의 안 하고 비흡연이에요. 주부이고 2주 회복 가능해요.",
             "slots": {"activityPattern": "거의 안함", "smoking": "false", "workConstraint": "주부", "recoveryAllowance": "2주"}},
            # Graph: p5AskDetail CHECKS [breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite]
            {"step": "p5AskDetail", "utterance": "유방암 이력 있어요. 전절제 수술 받았습니다. 보형물도 있어요. 복부 지방 있고 가슴 수술 3회 했어요. 가슴 부위예요.",
             "slots": {"breastCancerHistory": "true", "implantPresence": "true", "cancerSurgeryType": "완전",
                       "fatSourceAvailability": "복부", "pastOps": "가슴 수술 3회", "pastOpsSite": "가슴"}},
            # Graph: p5AskMedical CHECKS [implantCondition, implantOriginHospital] — collected (implantPresence=true)
            {"step": "p5AskMedical", "utterance": "보형물 상태는 파손이에요. B성형외과에서 했습니다.",
             "slots": {"implantCondition": "파손", "implantOriginHospital": "B성형외과"}},
            # p5InformSurgery: ruleCancerNotAllowed → NOT_ALLOWED
            {"step": "p5InformInfo", "utterance": "종합 사후관리 원하고 레이저 흉터 치료할게요. 위험성 상세 설명 부탁드려요.",
             "slots": {"aftercarePlan": "종합 사후관리", "scarManagement": "레이저 흉터 치료", "riskExplanationLevel": "상세"}},
            {"step": "p5Confirm", "utterance": "임소정이에요. 010-9090-1010입니다. 상담 후 결정할게요. 다음주 월요일에 방문하고 대안 시술 상담으로요.",
             "slots": {"customerName": "임소정", "phoneNumber": "010-9090-1010", "surgeryWindow": "상담 후 결정", "visitSchedule": "다음주 월요일", "procedurePlan": "대안 시술 상담"}},
        ],
    },

    # =========================================================================
    # 추가 시나리오: 엑셀 판단기준 문서의 식별 질문·배경 기반
    # =========================================================================

    # ── P1 운동선수 배경 (엑셀 §1.5 운동선수/피트니스 식별 질문) ──────
    "p1lf_athlete": {
        "name": "P1 슬림바디 - LOW-FAT (피트니스 배경, BMI<23, 가슴 지방이식 위해 증량 희망)",
        "persona": "slimBody",
        "scenario": "scenLowFat",
        "initial_utterance": "피트니스 대회 준비하면서 체지방이 많이 줄었는데, 대회 끝나고 가슴에 지방이식 받고 싶어요. 체지방이 부족할까 걱정이에요.",
        "expected_path": [
            "p1CollectInfo", "p1AskLifestyle", "p1AskDetail",
            "p1InformSurgery", "p1InformInfo", "p1Confirm",
        ],
        "branch_info": "BMI=19.5 (168cm 55kg) → LOW-FAT, weightGainIntent=true → collect(weightGainPlan, nutritionConsult) [운동선수 배경]",
        "turns": [
            {"step": "p1CollectInfo", "utterance": "168cm 55kg이에요. 체지방률은 12%이고 마른 근육질이에요. 인바디 데이터 있어요.",
             "slots": {"bodyInfo": "168cm 55kg", "bodyFat": "12", "bodyType": "마른 근육질", "inbodyAvailable": "true"}},
            {"step": "p1AskLifestyle", "utterance": "매일 웨이트 트레이닝해요. 운동 강도 매우 높고 고단백 식단 유지 중이에요. 대회 끝나면 가슴 지방이식 위해 체중 증량 할 수 있어요.",
             "slots": {"activityPattern": "매일 웨이트 트레이닝", "exerciseLevel": "매우 높음", "dietPattern": "고단백 식단", "weightGainIntent": "true"}},
            {"step": "p1AskDetail", "utterance": "옆구리에 약간 지방이 있고요, 복부는 거의 없어요. 시술 경험 없습니다.",
             "slots": {"fatSourceAvailability": "옆구리 소량", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p1InformSurgery → BMI 19.5 → ruleBodyFatLow → LOW-FAT
            {"step": "p1InformInfo", "utterance": "대회 후 2개월간 5kg 증량 목표로 하고 스포츠 영양사 상담도 받고 싶어요. 회복은 4주 압박복이요.",
             "slots": {"weightGainPlan": "2개월 5kg 증량 목표", "nutritionConsult": "스포츠 영양사 상담 희망", "recoveryGuideline": "4주 압박복"}},
            {"step": "p1Confirm", "utterance": "최서윤이에요. 010-4321-8765에요. 대회 끝나고 3개월 후에 가슴 수술하고, 한달 뒤에 재확인할게요.",
             "slots": {"customerName": "최서윤", "phoneNumber": "010-4321-8765", "surgeryWindow": "3개월 후", "recheckSchedule": "한달 뒤"}},
        ],
    },

    # ── P3 필러 이력자 (엑셀 §3.5 과거 시술 경험 식별 질문) ────────────
    "p3_filler_exp": {
        "name": "P3 피부시술 - 가슴성형 고려 중 피부관리 이력자 (선형)",
        "persona": "skinTreatment",
        "scenario": "scenAntiAging",
        "initial_utterance": "가슴 줄기세포 지방이식 전에 피부 탄력 관리를 하고 싶어요. 필러는 해봤는데 더 오래 유지되는 방법이 있을까요?",
        "expected_path": [
            "p3Collect", "p3AskLifestyle", "p3AskDetail",
            "p3AskSurgery", "p3InformSugery", "p3Confirm",
        ],
        "branch_info": "분기 없음 (선형) [필러/보톡스 경험자]",
        "turns": [
            {"step": "p3Collect", "utterance": "167cm 54kg이고 체지방 20%예요. 복합성 피부에 가슴 피부 탄력이 떨어지는 게 고민이고 수술 흉터도 걱정이에요.",
             "slots": {"bodyInfo": "167cm 54kg", "bodyFat": "20", "skinType": "복합성", "skinCondition": "가슴 피부 탄력 저하, 수술 흉터 우려"}},
            {"step": "p3AskLifestyle", "utterance": "필라테스 주 3회 해요. 실내 근무라 자외선 노출 적은 편이고 스킨케어 루틴이 있어요. 비흡연이에요.",
             "slots": {"activityPattern": "필라테스 주3회", "sunExposure": "낮음", "skincareRoutine": "스킨케어 루틴 있음", "smoking": "false"}},
            {"step": "p3AskDetail", "utterance": "허벅지에 지방 있고 필러 잔여물이 아직 좀 남아있어요. 알레르기 없고 필러 5회, 보톡스 4회 맞았어요. 팔자주름이랑 이마에 맞았고 4개월 주기로 했었어요.",
             "slots": {"fatSourceAvailability": "허벅지", "fillerRemaining": "약간 남아있음", "allergyHistory": "없음", "pastOps": "필러 5회, 보톡스 4회", "pastOpsSite": "팔자주름, 이마", "botoxCycle": "4개월 주기"}},
            {"step": "p3AskSurgery", "utterance": "가슴 지방이식 후 피부 탄력 개선이 제일 급하고 흉터 관리도 하고 싶어요. 자연스러운 가슴 라인과 피부 탄력 효과 원하고 최소 2년은 유지되면 좋겠어요.",
             "slots": {"concernArea": "가슴 피부 탄력, 수술 후 흉터 관리", "desiredEffect": "자연스러운 가슴 라인 + 피부 탄력", "durabilityExpectation": "최소 2년"}},
            # p3InformSugery: no checks
            {"step": "p3Confirm", "utterance": "김예진이에요. 010-7654-3210이요. 다음달 초에 하고 싶고 이번주 금요일 방문 가능해요. 줄기세포 지방이식이랑 리프팅 결합으로요.",
             "slots": {"customerName": "김예진", "phoneNumber": "010-7654-3210", "surgeryWindow": "다음달 초", "visitSchedule": "이번주 금요일", "procedurePlan": "가슴 줄기세포 지방이식 + 피부 탄력 시술"}},
        ],
    },

    # ── P4 국내 원거리 - 대전 S3 (엑셀 §4.4 Step 1 권역 식별) ─────────
    "p4semi_s3": {
        "name": "P4 원거리 - 대전 (SEMI-REMOTE S3 프로토콜, 가슴 지방이식)",
        "persona": "longDistance",
        "scenario": "scenRemote",
        "initial_utterance": "대전에서 사는데 가슴 줄기세포 지방이식 때문에 서울 내원이 부담돼요. 원거리 상담 가능한가요?",
        "expected_path": [
            "p4PreCollect", "p4Collect", "p4AskLifestyle", "p4AskDetail",
            "p4InformSurgery", "p4InformInfo", "p4Confirm", "p4Finalize",
        ],
        "branch_info": "residenceCountry=한국, domesticDistrict=대전 → regionBucket=S3 → SEMI-REMOTE",
        "turns": [
            {"step": "p4PreCollect", "utterance": "한국 대전에 살고 있어요. 주말 이용해서 2일 정도 서울 방문 가능하고 KTX로 이동합니다.",
             "slots": {"residenceCountry": "한국", "domesticDistrict": "대전", "visitPeriod": "2일", "travelConstraint": "KTX 이용"}},
            {"step": "p4Collect", "utterance": "160cm 53kg이고 체지방 22%예요. 인바디 없어요.",
             "slots": {"bodyInfo": "160cm 53kg", "bodyFat": "22", "inbodyAvailable": "false"}},
            {"step": "p4AskLifestyle", "utterance": "주2회 수영하고 중간 강도예요. 비흡연이고 1주 회복 가능합니다.",
             "slots": {"activityPattern": "주2회 수영", "exerciseLevel": "중간", "smoking": "false", "recoveryAllowance": "1주"}},
            {"step": "p4AskDetail", "utterance": "허벅지에서 지방 채취 가능하고 가슴 시술 이력 없습니다.",
             "slots": {"fatSourceAvailability": "허벅지", "pastOps": "없음", "pastOpsSite": "없음"}},
            # p4InformSurgery: no checks
            {"step": "p4InformInfo", "utterance": "사전검사 1시간이면 되고 사진이랑 서류 업로드했어요.",
             "slots": {"precheckTimeEstimate": "1시간", "bodyPhotoUpload": "uploaded", "documentUpload": "uploaded"}},
            {"step": "p4Confirm", "utterance": "다음주에 수술하고 보증금 예약합니다.",
             "slots": {"surgeryWindow": "다음주", "depositReservation": "true"}},
            {"step": "p4Finalize", "utterance": "장예린이에요. 010-3456-7890입니다. 대전 로컬 병원 연계 사후관리하고 2주 후 사진 원격 상담 받을게요.",
             "slots": {"customerName": "장예린", "phoneNumber": "010-3456-7890", "aftercarePlan": "대전 로컬 병원 연계", "followupSchedule": "2주 후 사진 원격 상담"}},
        ],
    },
}


# =============================================================================
# Layer 5: Step 체크포인트 완료도 검증
# =============================================================================

def verify_step_checkpoints(
    state: ConversationState,
    expected_path: list[str],
) -> list[tuple[str, str]]:
    """
    시나리오 실행 후, 각 step의 필수 슬롯이 모두 수집되었는지 검증.
    반환: [(step_id, missing_slot_name), ...] — 비어있으면 모두 충족.
    """
    missing: list[tuple[str, str]] = []
    filled = state.get_filled_slots()

    for step_id in expected_path:
        required = STEP_CHECKPOINT_REQUIREMENTS.get(step_id)
        if not required:
            continue  # inform step 등 체크포인트 없는 step

        for slot_name in required:
            # SYSTEM_MANAGED: protocolMode 등 → 자동 설정되므로 검증 제외
            if slot_name in SYSTEM_MANAGED_SLOTS:
                continue
            # AUTO_COMPUTABLE: bmi, regionBucket → 자동 계산되므로 검증 제외
            if slot_name in AUTO_COMPUTABLE_SLOTS:
                continue
            # 조건부 스킵: 조건 충족 시 수집 불필요
            skip_rule = CONDITIONAL_SKIP_RULES.get(slot_name)
            if skip_rule:
                when = skip_rule.get("when", {})
                should_skip = False
                for cond_slot, cond_val in when.items():
                    actual = filled.get(cond_slot, "")
                    if isinstance(cond_val, list):
                        if str(actual).lower() in [v.lower() for v in cond_val]:
                            should_skip = True
                    else:
                        if str(actual).lower() == str(cond_val).lower():
                            should_skip = True
                if should_skip:
                    continue

            # 실제 수집 여부 확인
            if slot_name not in filled:
                missing.append((step_id, slot_name))

    return missing


# =============================================================================
# REPL 엔진
# =============================================================================

def run_scenario_repl(
    engine: FlowEngine,
    scenario_key: str,
    step_by_step: bool = False,
    no_llm: bool = True,
    verbose: bool = False,
):
    """단일 시나리오를 REPL처럼 실행하면서 로그 출력"""

    sc = TEST_SCENARIOS[scenario_key]
    persona_id = sc["persona"]
    scenario_id = sc["scenario"]
    expected_path = sc["expected_path"]
    turns = sc["turns"]
    initial_utterance = sc.get("initial_utterance")

    print()
    print(header("=" * 72))
    print(header(f"  {sc['name']}"))
    print(header(f"  Persona: {persona_id} | Scenario: {scenario_id}"))
    print(header("=" * 72))
    print()

    # ── 초기 인사 + 고민 발화 (Turn 0) ──
    if initial_utterance:
        print(f"  {C.CYAN}🤖 Bot:{C.RESET} 안녕하세요! 성형외과 상담 챗봇입니다. 어떤 상담이 필요하신가요?")
        print(f"  {C.BLUE}👤 Turn 0:{C.RESET} {initial_utterance}")

        if no_llm:
            # no_llm 모드: 페르소나/시나리오를 직접 주입
            print(f"  {C.GRAY}📥 Persona 주입:{C.RESET} {ok(persona_id)} → Scenario: {ok(scenario_id)}")
        else:
            # LLM 모드: resolve_persona_scenario()로 페르소나 추론
            state_temp = ConversationState(session_id=f"repl_{scenario_key}")
            state_temp = engine.resolve_persona_scenario(state_temp, initial_utterance)
            inferred_persona = state_temp.persona_id
            inferred_scenario = state_temp.scenario_id
            if inferred_persona == persona_id:
                print(f"  {C.GRAY}📥 Persona 추론:{C.RESET} {ok(inferred_persona)} ✓")
            else:
                print(f"  {C.GRAY}📥 Persona 추론:{C.RESET} {err(inferred_persona)} (기대: {persona_id})")
            if inferred_scenario == scenario_id:
                print(f"  {C.GRAY}📥 Scenario 추론:{C.RESET} {ok(inferred_scenario)} ✓")
            else:
                print(f"  {C.GRAY}📥 Scenario 추론:{C.RESET} {err(inferred_scenario)} (기대: {scenario_id})")
        print()

    # State 초기화
    state = ConversationState(session_id=f"repl_{scenario_key}")
    state.persona_id = persona_id
    state.scenario_id = scenario_id

    # 시작 Step 결정
    scenario_data = engine.get_scenario(scenario_id)
    start_step = scenario_data.get("startStepId") if scenario_data else None
    if not start_step:
        print(err(f"  시작 Step을 찾을 수 없습니다: {scenario_id}"))
        return False

    state.current_step_id = start_step
    visited_steps = [start_step]
    turn_num = 0
    turn_idx = 0
    success = True

    while state.current_step_id and turn_idx <= len(turns):
        current_step = state.current_step_id
        step_info = engine.get_step(current_step)
        step_type = step_info.step_type if step_info else "?"
        checks = engine.get_step_checks(current_step)
        check_ids = [c.get("variableName") or c.get("id") for c in checks]

        # Step 헤더
        print(step_label(f"  ┌─ Step: {current_step}") + dim(f" (type={step_type})"))

        # CheckItem 목록
        if check_ids:
            skippable = []
            required = []
            auto = []
            for cid in check_ids:
                if engine.should_skip_check_item(cid, state):
                    skippable.append(cid)
                elif cid in AUTO_COMPUTABLE_SLOTS:
                    auto.append(cid)
                else:
                    required.append(cid)

            if required:
                print(dim(f"  │  수집 필요: ") + ", ".join(required))
            if auto:
                print(dim(f"  │  자동 계산: ") + ok(", ".join(auto)))
            if skippable:
                print(dim(f"  │  조건 스킵: ") + warn(", ".join(skippable)))
        else:
            print(dim(f"  │  (CheckItem 없음 - inform/finalize 단계)"))

        # 분기점 여부
        if current_step in BRANCHING_RULES:
            rules = BRANCHING_RULES[current_step]
            targets = list(set(r["targetStepId"] for r in rules))
            print(dim(f"  │  분기점: ") + ", ".join(targets))

        # 사용자 발화 찾기 (현재 Step에 해당하는 턴)
        turn_data = None
        for t in turns:
            if t["step"] == current_step:
                turn_data = t
                break

        if turn_data:
            turn_num += 1
            utterance = turn_data["utterance"]
            inject_slots = turn_data["slots"]

            print(dim(f"  │"))
            print(f"  │  {C.BLUE}👤 Turn {turn_num}:{C.RESET} {utterance[:80]}{'...' if len(utterance) > 80 else ''}")

            if no_llm:
                # LLM 없이 slot 직접 주입
                for k, v in inject_slots.items():
                    state.set_slot(k, v)
                print(f"  │  {C.GRAY}📥 Slots 주입:{C.RESET} ", end="")
                print(", ".join(slot_label(k, v) for k, v in inject_slots.items()))
            else:
                # 실제 LLM으로 slot 추출
                state = engine.extract_slots(state, utterance)
                extracted = {k: state.get_slot(k) for k in inject_slots if state.is_slot_filled(k)}
                missing = [k for k in inject_slots if not state.is_slot_filled(k)]
                print(f"  │  {C.GRAY}📥 LLM 추출:{C.RESET} ", end="")
                print(", ".join(slot_label(k, v) for k, v in extracted.items()))
                if missing:
                    print(f"  │  {err('⚠ LLM 미추출:')} {', '.join(missing)}")
                    # fallback: 미추출분 직접 주입
                    for k in missing:
                        state.set_slot(k, inject_slots[k])
                    print(f"  │  {dim('📥 Fallback 주입 완료')}")

            turn_idx += 1
        else:
            # 이 Step에 대한 턴 데이터가 없음 (inform 등 CheckItem 없는 Step)
            print(dim(f"  │"))
            print(dim(f"  │  (사용자 입력 불필요)"))

        # 자동 계산
        auto_computed = engine.auto_compute_slots(state)
        if auto_computed:
            print(f"  │  {ok('🧮 자동 계산:')} ", end="")
            print(", ".join(slot_label(k, state.get_slot(k)) for k in auto_computed))

        # 다음 Step 결정
        transition = engine.next_step(state)

        # protocolMode 반영
        if transition.protocol_mode:
            state.set_slot("protocolMode", transition.protocol_mode)
            print(f"  │  {ok('🔀 protocolMode =')} {transition.protocol_mode}")

        # 전이 결과 출력
        via = transition.via
        next_id = transition.next_step_id

        if via == "stay":
            print(f"  │  {warn('⏸ 머무름:')} {transition.debug}")
            # stay면 다음 턴 데이터로 slot 보충 시도
            if turn_idx < len(turns):
                continue
            else:
                print(f"  └─ {err('✗ 더 이상 턴 데이터 없음 - 시나리오 실패')}")
                success = False
                break
        elif via == "branching":
            rule_info = transition.debug.get("ruleId", transition.debug.get("transitionId", ""))
            print(f"  │  {ok('🔀 분기:')} {rule_info} → {next_id}")
        elif via == "to":
            print(f"  │  {ok('➡ 전이:')} → {next_id}")
        elif via == "end":
            print(f"  └─ {ok('✓ 시나리오 종료')}")
            break
        else:
            print(f"  │  {dim(f'전이: {via}')} → {next_id}")

        print(f"  └─ {dim(f'slots: {len(state.get_filled_slots())}개 수집됨')}")
        print()

        if next_id:
            state.move_to_step(next_id)
            visited_steps.append(next_id)
        else:
            break

        if step_by_step:
            try:
                input(dim("  [Enter로 계속...]"))
            except KeyboardInterrupt:
                print("\n중단됨.")
                return False

    # 결과 요약
    print()
    print(header("  ── 결과 요약 ──"))
    print(f"  방문 경로: {' → '.join(visited_steps)}")
    print(f"  기대 경로: {' → '.join(expected_path)}")

    path_match = visited_steps == expected_path
    if path_match:
        print(f"  경로 일치: {ok('✓ PASS')}")
    else:
        print(f"  경로 일치: {err('✗ FAIL')}")
        success = False

    print(f"  수집된 Slots: {len(state.get_filled_slots())}개")

    if verbose:
        print(f"\n  {dim('전체 Slot 목록:')}")
        for k, v in sorted(state.get_filled_slots().items()):
            print(f"    {slot_label(k, v)}")

    protocol = state.get_slot("protocolMode")
    if protocol:
        print(f"  protocolMode: {ok(protocol)}")

    bmi = state.get_slot("bmi")
    if bmi:
        print(f"  BMI: {ok(str(bmi))}")

    rb = state.get_slot("regionBucket")
    if rb:
        print(f"  regionBucket: {ok(rb)}")

    # ── Layer 5: Step 체크포인트 완료도 검증 ──
    checkpoint_missing = verify_step_checkpoints(state, expected_path)
    if checkpoint_missing:
        print(f"\n  {warn('⚠ 체크포인트 미충족 슬롯:')}")
        for step_id, slot_name in checkpoint_missing:
            print(f"    {warn('·')} {step_id}/{slot_name}")
    else:
        print(f"  체크포인트: {ok('✓ 모든 필수 슬롯 수집 완료')}")

    print()
    return success


# =============================================================================
# 대화형 모드 (수동 입력)
# =============================================================================

def run_interactive(engine: FlowEngine, persona_id: str, scenario_id: str):
    """수동 입력 REPL - 직접 타이핑하면서 로그 트래킹"""

    print()
    print(header("=" * 60))
    print(header(f"  대화형 모드: {persona_id}/{scenario_id}"))
    print(header("  명령어: /state /slots /step /quit"))
    print(header("=" * 60))
    print()

    state = ConversationState(session_id=f"interactive_{persona_id}")
    state.persona_id = persona_id
    state.scenario_id = scenario_id

    scenario_data = engine.get_scenario(scenario_id)
    start_step = scenario_data.get("startStepId") if scenario_data else None
    state.current_step_id = start_step

    turn_num = 0

    while state.current_step_id:
        current = state.current_step_id
        step_info = engine.get_step(current)
        checks = engine.get_step_checks(current)
        check_ids = [c.get("variableName") or c.get("id") for c in checks]

        # 상태 표시
        print(step_label(f"  [Step: {current}]") + dim(f" checks={check_ids}"))

        # 미수집 항목
        missing = []
        for cid in check_ids:
            if state.is_slot_filled(cid):
                continue
            if engine.should_skip_check_item(cid, state):
                continue
            if cid in AUTO_COMPUTABLE_SLOTS:
                continue
            missing.append(cid)

        if missing:
            print(dim(f"  미수집: {missing}"))

        if not check_ids:
            print(dim("  (입력 불필요 - 자동 전이)"))
            engine.auto_compute_slots(state)
            transition = engine.next_step(state)
            if transition.protocol_mode:
                state.set_slot("protocolMode", transition.protocol_mode)
                print(ok(f"  protocolMode = {transition.protocol_mode}"))
            if transition.next_step_id:
                print(ok(f"  → {transition.next_step_id}"))
                state.move_to_step(transition.next_step_id)
            else:
                print(ok("  시나리오 종료"))
                break
            print()
            continue

        try:
            user_input = input(f"  {C.BLUE}👤 You:{C.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n종료.")
            break

        if user_input.lower() in ("/quit", "quit", "exit"):
            break
        if user_input == "/state":
            print(f"  persona={state.persona_id}, scenario={state.scenario_id}")
            print(f"  step={state.current_step_id}")
            print(f"  protocolMode={state.get_slot('protocolMode')}")
            continue
        if user_input == "/slots":
            for k, v in sorted(state.get_filled_slots().items()):
                print(f"    {slot_label(k, v)}")
            continue
        if user_input == "/step":
            print(f"  {current}: checks={check_ids}")
            continue
        if not user_input:
            continue

        turn_num += 1

        # Slot 추출 (LLM 사용)
        state = engine.extract_slots(state, user_input)
        engine.auto_compute_slots(state)

        # 새로 채워진 slot 표시
        filled = state.get_filled_slots()
        print(f"  {dim('slots:')} {len(filled)}개")

        transition = engine.next_step(state)
        if transition.protocol_mode:
            state.set_slot("protocolMode", transition.protocol_mode)
            print(ok(f"  protocolMode = {transition.protocol_mode}"))

        if transition.via == "stay":
            print(warn(f"  ⏸ 머무름: {transition.debug.get('reason', '')}"))
        elif transition.next_step_id:
            print(ok(f"  → {transition.next_step_id} (via={transition.via})"))
            state.move_to_step(transition.next_step_id)
        else:
            print(ok("  시나리오 종료"))
            break
        print()

    print(f"\n  총 {turn_num}턴, slots {len(state.get_filled_slots())}개")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="SC301 테스트 시나리오 REPL")
    parser.add_argument("--db", choices=["local", "aura"], default="local")
    parser.add_argument("--scenario", "-s", help="시나리오 키 (p1std, p1lf, p1lf_nogain, p2a, p2b_stem, p2b_general, p3, p4abroad, p4semi, p4std, p5_std, p5_std_implant, p5_conditional, p5_not_allowed, all)")
    parser.add_argument("--interactive", "-i", action="store_true", help="수동 입력 모드")
    parser.add_argument("--step", action="store_true", help="턴마다 일시정지")
    parser.add_argument("--no-llm", action="store_true", default=True, help="LLM 없이 slot 직접 주입 (기본)")
    parser.add_argument("--with-llm", action="store_true", help="실제 LLM으로 slot 추출")
    parser.add_argument("--model", choices=["gpt-4o", "gpt-5"], default=None,
                        help="챗봇 응답 모델 (기본: .env의 OPENAI_CHAT_MODEL)")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그")

    args = parser.parse_args()

    if args.with_llm:
        args.no_llm = False

    # DB 연결
    if args.db == "local":
        uri = "bolt://localhost:7687"
        auth = ("neo4j", "password")
    else:
        uri = os.environ.get("NEO4J_AURA_URI", "")
        auth = (os.environ.get("NEO4J_AURA_USER", ""), os.environ.get("NEO4J_AURA_PASSWORD", ""))

    driver = GraphDatabase.driver(uri, auth=auth)

    # OpenAI 클라이언트 (LLM 모드일 때만)
    openai_client = None
    chat_model = "gpt-4o"
    slot_model = "gpt-4o-mini"
    if not args.no_llm:
        from openai import OpenAI
        openai_client = OpenAI()
        # --model 인자 우선, 없으면 .env 값
        if args.model:
            chat_model = args.model
            slot_model = args.model + "-mini"  # gpt-4o → gpt-4o-mini, gpt-5 → gpt-5-mini
        else:
            chat_model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o")
            slot_model = os.environ.get("SLOT_EXTRACTION_MODEL", "gpt-4o-mini")
        print(dim(f"  모델: 응답={chat_model}, 슬롯추출={slot_model}"))

    engine = FlowEngine(
        driver=driver,
        openai_client=openai_client,
        chat_model=chat_model,
        slot_extraction_model=slot_model,
    )

    if args.interactive:
        # 시나리오 선택
        print("\n사용 가능한 시나리오:")
        for key, sc in TEST_SCENARIOS.items():
            print(f"  {key}: {sc['name']}")
        choice = input("\n시나리오 키 입력: ").strip()
        if choice not in TEST_SCENARIOS:
            print(f"알 수 없는 시나리오: {choice}")
            sys.exit(1)
        sc = TEST_SCENARIOS[choice]
        run_interactive(engine, sc["persona"], sc["scenario"])

    elif args.scenario:
        if args.scenario == "all":
            total_pass = 0
            total_fail = 0
            for key in TEST_SCENARIOS:
                engine.clear_cache()
                ok_result = run_scenario_repl(
                    engine, key,
                    step_by_step=args.step,
                    no_llm=args.no_llm,
                    verbose=args.verbose,
                )
                if ok_result:
                    total_pass += 1
                else:
                    total_fail += 1

            print(header("=" * 72))
            print(header(f"  전체 결과: {total_pass} PASS, {total_fail} FAIL (총 {len(TEST_SCENARIOS)}개)"))
            print(header("=" * 72))
            sys.exit(0 if total_fail == 0 else 1)
        else:
            if args.scenario not in TEST_SCENARIOS:
                print(f"알 수 없는 시나리오: {args.scenario}")
                print(f"사용 가능: {', '.join(TEST_SCENARIOS.keys())}")
                sys.exit(1)
            engine.clear_cache()
            ok_result = run_scenario_repl(
                engine, args.scenario,
                step_by_step=args.step,
                no_llm=args.no_llm,
                verbose=args.verbose,
            )
            sys.exit(0 if ok_result else 1)

    else:
        # 시나리오 목록 표시
        print("\n사용 가능한 시나리오:")
        for key, sc in TEST_SCENARIOS.items():
            print(f"  {key:12s} {sc['name']}")
        print(f"\n사용법:")
        print(f"  python test_repl.py -s p1std          # P1 STANDARD 실행")
        print(f"  python test_repl.py -s all             # 전체 실행")
        print(f"  python test_repl.py -s p1std --step    # 턴마다 일시정지")
        print(f"  python test_repl.py -s all -v          # 상세 로그")
        print(f"  python test_repl.py -i                 # 수동 입력 모드")
        print(f"  python test_repl.py -s p1std --with-llm              # LLM으로 실행 (.env 모델)")
        print(f"  python test_repl.py -s p1std --with-llm --model gpt-4o  # gpt-4o로 실행")
        print(f"  python test_repl.py -s p1std --with-llm --model gpt-5   # gpt-5로 실행")

    driver.close()


if __name__ == "__main__":
    main()
