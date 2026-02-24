"""
test_scenarios.py - 페르소나별 전체 플로우 통과 테스트

각 Persona/Scenario에 대해:
1. 첫 Step부터 마지막 Step까지 전이가 정상적으로 이루어지는지 검증
2. 자동 계산(BMI, regionBucket) 동작 확인
3. 조건부 스킵(implant, weightGain 등) 동작 확인
4. BRANCHING_RULES 분기 검증
5. protocolMode 자동 설정 확인

실행: python test_scenarios.py
"""

from __future__ import annotations

import sys
from typing import Optional, Dict, List
from neo4j import GraphDatabase
from flow import FlowEngine
from state import ConversationState
from schema import BRANCHING_RULES

# ===========================================================================
# 설정
# ===========================================================================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "password")

PASS = "✓"
FAIL = "✗"


def make_state(
    persona_id: str,
    scenario_id: str,
    step_id: str,
    slots: dict | None = None,
) -> ConversationState:
    """테스트용 ConversationState 생성"""
    state = ConversationState(
        session_id=f"test_{persona_id}_{step_id}",
        persona_id=persona_id,
        scenario_id=scenario_id,
        current_step_id=step_id,
    )
    if slots:
        for k, v in slots.items():
            state.set_slot(k, v)
    return state


# ===========================================================================
# 테스트 유틸리티
# ===========================================================================

def walk_scenario(
    engine: FlowEngine,
    persona_id: str,
    scenario_id: str,
    slot_feeder: dict[str, dict],
    description: str,
) -> list[str]:
    """
    시나리오를 처음부터 끝까지 걸어가면서 Step 전이를 검증.

    slot_feeder: { step_id: { slot_name: value, ... } }
        각 Step에 도달했을 때 사용자가 입력한 것처럼 slot을 채워줌.

    Returns: 방문한 step_id 리스트
    """
    # 시작 Step 결정
    scenario = engine.get_scenario(scenario_id)
    assert scenario is not None, f"시나리오 {scenario_id} 없음"
    start_step = scenario.get("startStepId")
    assert start_step, f"시나리오 {scenario_id} 시작 Step 없음"

    state = make_state(persona_id, scenario_id, start_step)
    visited = [start_step]
    max_iterations = 20  # 무한루프 방지

    for i in range(max_iterations):
        current = state.current_step_id
        if current is None:
            break

        # 해당 Step의 slot을 채워줌
        if current in slot_feeder:
            for k, v in slot_feeder[current].items():
                state.set_slot(k, v)

        # 자동 계산
        engine.auto_compute_slots(state)

        # 다음 Step 결정
        transition = engine.next_step(state)

        # protocolMode 반영
        if transition.protocol_mode:
            state.set_slot("protocolMode", transition.protocol_mode)

        if transition.via == "stay":
            # 아직 slot이 부족하면 실패
            checks = engine.get_step_checks(current)
            missing = []
            for ci in checks:
                vn = ci.get("variableName") or ci.get("name") or ci.get("id")
                if vn and not state.is_slot_filled(vn) and not engine.should_skip_check_item(vn, state):
                    from schema import AUTO_COMPUTABLE_SLOTS
                    if vn not in AUTO_COMPUTABLE_SLOTS:
                        missing.append(vn)
            assert False, (
                f"Step '{current}'에서 머무름 (stay). "
                f"미수집: {missing}, transition.debug={transition.debug}"
            )

        if transition.next_step_id:
            state.move_to_step(transition.next_step_id)
            visited.append(transition.next_step_id)
        else:
            # 종료
            break

    return visited


# ===========================================================================
# Persona 1: slimBody (scenLowFat) - BMI 기반 분기
# ===========================================================================

def test_persona1_standard(engine: FlowEngine):
    """P1 slimBody: BMI >= 23 → STANDARD 경로"""
    slot_feeder = {
        "p1CollectInfo": {
            "bodyInfo": "165cm 71kg",   # BMI 26.1 → STANDARD
            "bodyFat": "30",
            "bodyType": "보통",
            "inbodyAvailable": "true",
        },
        "p1AskLifestyle": {
            "activityPattern": "주3회 운동",
            "exerciseLevel": "중간",
            "dietPattern": "불규칙",
            "weightGainIntent": "false",
        },
        "p1AskDetail": {
            "fatSourceAvailability": "복부, 허벅지",
            "pastOps": "없음",
            "pastOpsSite": "없음",
        },
        # p1InformSurgery: checks 없음 → BMI 분기 (STANDARD)
        "p1InformInfo": {
            "weightGainPlan": "해당없음",   # weightGainIntent=false이므로 skip 대상이지만 값 넣어도 무방
            "nutritionConsult": "해당없음",  # 마찬가지
            "recoveryGuideline": "2주 압박복 착용",
        },
        "p1Confirm": {
            "customerName": "김지현",
            "phoneNumber": "010-9876-5432",
            "surgeryWindow": "다음달",
            "recheckSchedule": "2주 후",
        },
    }

    visited = walk_scenario(engine, "slimBody", "scenLowFat", slot_feeder, "P1 STANDARD")

    expected = [
        "p1CollectInfo", "p1AskLifestyle", "p1AskDetail",
        "p1InformSurgery", "p1InformInfo", "p1Confirm",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    # BMI 자동 계산 검증
    state = make_state("slimBody", "scenLowFat", "p1InformSurgery",
                        {"bodyInfo": "175cm 80kg"})
    engine.auto_compute_slots(state)
    bmi = state.get_slot("bmi")
    assert bmi is not None and bmi >= 23, f"BMI={bmi}, 23 이상이어야 STANDARD"

    # protocolMode 검증
    transition = engine.next_step(state)
    assert transition.protocol_mode == "STANDARD", f"Expected STANDARD, got {transition.protocol_mode}"

    return True


def test_persona1_lowfat(engine: FlowEngine):
    """P1 slimBody: BMI < 23 → LOW-FAT 경로"""
    slot_feeder = {
        "p1CollectInfo": {
            "bodyInfo": "165cm 55kg",  # BMI 20.2 → LOW-FAT
            "bodyFat": "18",
            "bodyType": "마른체형",
            "inbodyAvailable": "false",
        },
        "p1AskLifestyle": {
            "activityPattern": "거의 안함",
            "exerciseLevel": "낮음",
            "dietPattern": "소식",
            "weightGainIntent": "true",
        },
        "p1AskDetail": {
            "fatSourceAvailability": "허벅지 소량",
            "pastOps": "없음",
            "pastOpsSite": "없음",
        },
        # p1InformSurgery: BMI 분기 (LOW-FAT)
        "p1InformInfo": {
            "weightGainPlan": "한달 3kg 증량 목표",
            "nutritionConsult": "영양사 상담 희망",
            "recoveryGuideline": "3주 압박복",
        },
        "p1Confirm": {
            "customerName": "이수진",
            "phoneNumber": "010-1111-2222",
            "surgeryWindow": "2개월 후",
            "recheckSchedule": "1개월 후",
        },
    }

    visited = walk_scenario(engine, "slimBody", "scenLowFat", slot_feeder, "P1 LOW-FAT")

    expected = [
        "p1CollectInfo", "p1AskLifestyle", "p1AskDetail",
        "p1InformSurgery", "p1InformInfo", "p1Confirm",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    # BMI 자동 계산 + LOW-FAT 분기 검증
    state = make_state("slimBody", "scenLowFat", "p1InformSurgery",
                        {"bodyInfo": "165cm 55kg"})
    engine.auto_compute_slots(state)
    bmi = state.get_slot("bmi")
    assert bmi is not None and bmi < 23, f"BMI={bmi}, 23 미만이어야 LOW-FAT"

    transition = engine.next_step(state)
    assert transition.protocol_mode == "LOW-FAT", f"Expected LOW-FAT, got {transition.protocol_mode}"

    return True


def test_persona1_skip_pastopssite(engine: FlowEngine):
    """P1: pastOps="없음" → pastOpsSite 스킵 확인"""
    # pastOps가 "없음"이면 pastOpsSite는 스킵 대상
    state_no_ops = make_state("slimBody", "scenLowFat", "p1AskDetail", {
        "pastOps": "없음",
    })
    assert engine.should_skip_check_item("pastOpsSite", state_no_ops) == True

    # pastOps가 "없습니다"여도 스킵
    state_no_ops2 = make_state("slimBody", "scenLowFat", "p1AskDetail", {
        "pastOps": "없습니다",
    })
    assert engine.should_skip_check_item("pastOpsSite", state_no_ops2) == True

    # pastOps가 실제 값이면 스킵 안 됨
    state_has_ops = make_state("slimBody", "scenLowFat", "p1AskDetail", {
        "pastOps": "가슴 확대 1회",
    })
    assert engine.should_skip_check_item("pastOpsSite", state_has_ops) == False

    return True


def test_persona1_skip_weightgain(engine: FlowEngine):
    """P1: weightGainIntent=false → weightGainPlan, nutritionConsult 스킵 확인"""
    state = make_state("slimBody", "scenLowFat", "p1InformInfo", {
        "weightGainIntent": "false",
        "recoveryGuideline": "2주",
    })

    # weightGainPlan, nutritionConsult는 스킵 대상
    assert engine.should_skip_check_item("weightGainPlan", state) == True
    assert engine.should_skip_check_item("nutritionConsult", state) == True

    # recoveryGuideline만 있으면 step 통과
    assert engine._are_step_checks_filled("p1InformInfo", state) == True

    return True


# ===========================================================================
# Persona 2: lipoCustomer (scenLipoGraft) - upsellAccept 분기
# ===========================================================================

def test_persona2_lipo_only(engine: FlowEngine):
    """P2 lipoCustomer: upsellAccept=false → p2InformInfoA (흡입 단독)"""
    slot_feeder = {
        "p2PreCollect": {
            "bodyInfo": "170cm 70kg",
            "schedule": "다음주 화요일",
            "concernArea": "가슴 볼륨",
            "medicalHistory": "없음",
            "basicInfo": "서지영 010-1234-5678",
        },
        "p2Collect": {
            "bodyInfo": "170cm 70kg",  # 중복이지만 이미 있으니 스킵됨
            "schedule": "다음주 화요일",
            "travelConstraint": "없음",
        },
        "p2AskLifestyle": {
            "activityPattern": "주5회 운동",
            "exerciseLevel": "높음",
            "smoking": "false",
            "recoveryAllowance": "2주",
            "jobIntensity": "사무직",
        },
        "p2AskDetail": {
            "fatSourceAvailability": "복부 충분",
            "lipoArea": "복부, 옆구리",
            "lipoGoal": "가슴 볼륨 업",
            "riskFactor": "없음",
            "pastOps": "없음",
        },
        "p2InformSurgery": {
            "planPreference": "흡입 단독",
            "upsellAccept": "false",  # → p2InformInfoA
            "concernSideEffect": "멍",
            "costSensitivity": "중간",
            "recoveryAllowance": "2주",
        },
        "p2InformInfoA": {
            "recoveryTimeline": "2주 압박복",
            "lipoPlanDetail": "복부 전체 흡입",
            "costRange": "300-500만원",
        },
        "p2Finalize": {
            "precheckRequired": "true",
            "visitSchedule": "다음주 목요일",
            "sameDayPossible": "false",
            "reservationIntent": "true",
        },
    }

    visited = walk_scenario(engine, "lipoCustomer", "scenLipoGraft", slot_feeder, "P2 흡입단독")

    expected = [
        "p2PreCollect", "p2Collect", "p2AskLifestyle", "p2AskDetail",
        "p2InformSurgery", "p2InformInfoA", "p2Finalize",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona2_lipo_plus_transfer(engine: FlowEngine):
    """P2 lipoCustomer: upsellAccept=true → p2InformInfoB (흡입+이식)"""
    slot_feeder = {
        "p2PreCollect": {
            "bodyInfo": "168cm 65kg",
            "schedule": "이번주 금요일",
            "concernArea": "가슴 볼륨",
            "medicalHistory": "없음",
            "basicInfo": "이영희 010-5678-1234",
        },
        "p2Collect": {
            "bodyInfo": "168cm 65kg",
            "schedule": "이번주 금요일",
            "travelConstraint": "없음",
        },
        "p2AskLifestyle": {
            "activityPattern": "주2회",
            "exerciseLevel": "중간",
            "smoking": "false",
            "recoveryAllowance": "3주",
            "jobIntensity": "프리랜서",
        },
        "p2AskDetail": {
            "fatSourceAvailability": "허벅지",
            "lipoArea": "허벅지 안쪽",
            "lipoGoal": "가슴 이식용 지방 확보",
            "riskFactor": "없음",
            "pastOps": "없음",
        },
        "p2InformSurgery": {
            "planPreference": "흡입+이식",
            "upsellAccept": "true",  # → p2InformInfoB
            "concernSideEffect": "부기",
            "costSensitivity": "낮음",
            "recoveryAllowance": "3주",
        },
        "p2InformInfoB": {
            "transferType": "일반",  # 일반 이식 선택
            "transferPlanDetail": "일반 이식 가슴 볼륨 보충",
            "recoveryTimeline": "3주 회복",
            "graftExpectation": "자연스러운 가슴 볼륨",
            "costRange": "500-700만원",
        },
        "p2Finalize": {
            "precheckRequired": "true",
            "visitSchedule": "다음주 월요일",
            "sameDayPossible": "true",
            "reservationIntent": "true",
        },
    }

    visited = walk_scenario(engine, "lipoCustomer", "scenLipoGraft", slot_feeder, "P2 흡입+이식(일반)")

    expected = [
        "p2PreCollect", "p2Collect", "p2AskLifestyle", "p2AskDetail",
        "p2InformSurgery", "p2InformInfoB", "p2Finalize",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona2_stemcell_transfer(engine: FlowEngine):
    """P2 lipoCustomer: upsellAccept=true, transferType=줄기세포"""
    state = make_state("lipoCustomer", "scenLipoGraft", "p2InformInfoB", {
        "upsellAccept": "true",
        "transferType": "줄기세포",
        "transferPlanDetail": "줄기세포 이식 가슴 볼륨 보충",
        "recoveryTimeline": "4주",
        "graftExpectation": "줄기세포 이식",
        "costRange": "800-1200만원",
    })

    transition = engine.next_step(state)
    # p2InformInfoB에서 transferType 기반 분기 → p2Finalize
    assert transition.next_step_id == "p2Finalize", (
        f"Expected p2Finalize, got {transition.next_step_id} via={transition.via}"
    )

    return True


# ===========================================================================
# Persona 3: skinTreatment (scenAntiAging) - 선형 흐름
# ===========================================================================

def test_persona3_full(engine: FlowEngine):
    """P3 skinTreatment: 전체 선형 플로우"""
    slot_feeder = {
        "p3Collect": {
            "bodyInfo": "162cm 50kg",
            "bodyFat": "22",
            "skinType": "건성",
            "skinCondition": "가슴 부위 탄력 저하, 흉터 우려",
        },
        "p3AskLifestyle": {
            "activityPattern": "요가 주2회",
            "sunExposure": "높음 (야외 근무)",
            "skincareRoutine": "기초 화장품만 사용",
            "smoking": "false",
        },
        "p3AskDetail": {
            "fatSourceAvailability": "허벅지",
            "fillerRemaining": "false",
            "allergyHistory": "없음",
            "pastOps": "보톡스 3회",
            "pastOpsSite": "이마, 눈가",
            "botoxCycle": "6개월 주기",
        },
        "p3AskSurgery": {
            "concernArea": "가슴 피부 탄력, 수술 후 흉터",
            "desiredEffect": "자연스러운 가슴 라인 + 피부결 개선",
            "durabilityExpectation": "1년 이상",
        },
        # p3InformSugery: checks 없음
        "p3Confirm": {
            "customerName": "최윤아",
            "phoneNumber": "010-4444-5555",
            "surgeryWindow": "이번달 내",
            "visitSchedule": "다음주 수요일",
            "procedurePlan": "줄기세포 지방이식 + 피부 탄력 시술",
        },
    }

    visited = walk_scenario(engine, "skinTreatment", "scenAntiAging", slot_feeder, "P3 전체")

    expected = [
        "p3Collect", "p3AskLifestyle", "p3AskDetail",
        "p3AskSurgery", "p3InformSugery", "p3Confirm",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


# ===========================================================================
# Persona 4: longDistance (scenRemote) - regionBucket 자동 계산 + protocolMode
# ===========================================================================

def test_persona4_abroad(engine: FlowEngine):
    """P4 longDistance: 해외 거주 → FULL 프로토콜"""
    slot_feeder = {
        "p4PreCollect": {
            "residenceCountry": "ABROAD",
            # domesticDistrict: 해외이므로 스킵 대상
            # regionBucket: ABROAD 자동 계산
            "visitPeriod": "2주",
            "travelConstraint": "비자 필요",
        },
        "p4Collect": {
            "bodyInfo": "172cm 68kg",
            "bodyFat": "20",
            "inbodyAvailable": "false",
            # inbodyPhotoUpload: inbodyAvailable=false이므로 스킵 대상
        },
        "p4AskLifestyle": {
            "activityPattern": "주3회 조깅",
            "exerciseLevel": "중간",
            "smoking": "false",
            "recoveryAllowance": "3주",
        },
        "p4AskDetail": {
            "fatSourceAvailability": "복부",
            "pastOps": "없음",
            "pastOpsSite": "없음",
        },
        # p4InformSurgery: checks 없음
        "p4InformInfo": {
            "precheckTimeEstimate": "2시간",
            "bodyPhotoUpload": "uploaded",
            "documentUpload": "uploaded",
        },
        "p4Confirm": {
            "surgeryWindow": "다음달",
            "depositReservation": "true",
        },
        "p4Finalize": {
            "customerName": "정하나",
            "phoneNumber": "010-6666-7777",
            "aftercarePlan": "현지 병원 연계",
            "followupSchedule": "수술 후 2주 원격 상담",
        },
    }

    visited = walk_scenario(engine, "longDistance", "scenRemote", slot_feeder, "P4 해외")

    expected = [
        "p4PreCollect", "p4Collect", "p4AskLifestyle", "p4AskDetail",
        "p4InformSurgery", "p4InformInfo", "p4Confirm", "p4Finalize",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona4_semiremote(engine: FlowEngine):
    """P4 longDistance: 국내 원거리 (부산) → SEMI-REMOTE 프로토콜"""
    slot_feeder = {
        "p4PreCollect": {
            "residenceCountry": "한국",
            "domesticDistrict": "부산",
            # regionBucket: S4 자동 계산 → SEMI-REMOTE
            "visitPeriod": "3일",
            "travelConstraint": "KTX 이용",
        },
        "p4Collect": {
            "bodyInfo": "162cm 56kg",
            "bodyFat": "25",
            "inbodyAvailable": "true",
            "inbodyPhotoUpload": "uploaded",
        },
        "p4AskLifestyle": {
            "activityPattern": "주3회 필라테스",
            "exerciseLevel": "높음",
            "smoking": "false",
            "recoveryAllowance": "1주",
        },
        "p4AskDetail": {
            "fatSourceAvailability": "복부, 허벅지",
            "pastOps": "없음",
            "pastOpsSite": "없음",
        },
        "p4InformSurgery": {},
        "p4InformInfo": {
            "precheckTimeEstimate": "1시간",
            "bodyPhotoUpload": "uploaded",
            "documentUpload": "uploaded",
        },
        "p4Confirm": {
            "surgeryWindow": "이번달",
            "depositReservation": "true",
        },
        "p4Finalize": {
            "customerName": "윤다혜",
            "phoneNumber": "010-8888-9999",
            "aftercarePlan": "지역 병원 연계",
            "followupSchedule": "1주 후 재방문",
        },
    }

    visited = walk_scenario(engine, "longDistance", "scenRemote", slot_feeder, "P4 국내원거리")

    expected = [
        "p4PreCollect", "p4Collect", "p4AskLifestyle", "p4AskDetail",
        "p4InformSurgery", "p4InformInfo", "p4Confirm", "p4Finalize",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona4_standard(engine: FlowEngine):
    """P4 longDistance: 서울 거주 → STANDARD 프로토콜 (default)"""
    state = make_state("longDistance", "scenRemote", "p4PreCollect", {
        "residenceCountry": "한국",
        "domesticDistrict": "서울",
        "visitPeriod": "당일",
        "travelConstraint": "없음",
    })
    engine.auto_compute_slots(state)

    rb = state.get_slot("regionBucket")
    assert rb == "S1", f"Expected S1, got {rb}"

    transition = engine.next_step(state)
    # S1 → default 규칙 매칭 → STANDARD
    assert transition.via == "branching", f"Expected branching, got {transition.via}"

    return True


def test_persona4_region_autocalc(engine: FlowEngine):
    """P4: regionBucket 자동 계산 + domesticDistrict 스킵 확인"""
    # 해외: domesticDistrict 스킵
    state_abroad = make_state("longDistance", "scenRemote", "p4PreCollect", {
        "residenceCountry": "ABROAD",
    })
    assert engine.should_skip_check_item("domesticDistrict", state_abroad) == True
    engine.auto_compute_slots(state_abroad)
    assert state_abroad.get_slot("regionBucket") == "ABROAD"

    # 국내: domesticDistrict 필요
    state_domestic = make_state("longDistance", "scenRemote", "p4PreCollect", {
        "residenceCountry": "한국",
    })
    assert engine.should_skip_check_item("domesticDistrict", state_domestic) == False

    # 국내 + 지역 있으면 자동 매핑
    state_domestic.set_slot("domesticDistrict", "경기")
    engine.auto_compute_slots(state_domestic)
    assert state_domestic.get_slot("regionBucket") == "S2"

    return True


def test_persona4_inbody_skip(engine: FlowEngine):
    """P4: inbodyAvailable=false → inbodyPhotoUpload 스킵"""
    state = make_state("longDistance", "scenRemote", "p4Collect", {
        "inbodyAvailable": "false",
    })
    assert engine.should_skip_check_item("inbodyPhotoUpload", state) == True

    state2 = make_state("longDistance", "scenRemote", "p4Collect", {
        "inbodyAvailable": "true",
    })
    assert engine.should_skip_check_item("inbodyPhotoUpload", state2) == False

    return True


# ===========================================================================
# Persona 5: revisionFatigue (scenRevision) - 암/보형물 조건부 스킵
# ===========================================================================

def test_persona5_no_cancer_no_implant(engine: FlowEngine):
    """P5: 유방암 없음 + 보형물 없음 → implantCondition/Hospital 스킵, STANDARD"""
    slot_feeder = {
        "p5Collect": {
            "bodyInfo": "160cm 55kg",
            "bodyFat": "24",
            "bodyType": "보통",
        },
        "p5AskLifestyle": {
            "activityPattern": "가끔 산책",
            "smoking": "false",
            "workConstraint": "사무직",
            "recoveryAllowance": "2주",
        },
        "p5AskDetail": {
            "breastCancerHistory": "false",
            "implantPresence": "false",
            "cancerSurgeryType": "해당없음",
            "fatSourceAvailability": "복부",
            "pastOps": "가슴 확대 1회",
            "pastOpsSite": "가슴",
        },
        "p5AskMedical": {
            # implantCondition: 스킵 (implantPresence=false)
            # implantOriginHospital: 스킵 (implantPresence=false)
        },
        # p5InformSurgery: checks 없음 → ruleCancerNone → STANDARD
        "p5InformInfo": {
            "aftercarePlan": "정기 검진",
            "scarManagement": "실리콘 시트",
            "riskExplanationLevel": "상세",
        },
        "p5Confirm": {
            "customerName": "강미래",
            "phoneNumber": "010-7777-8888",
            "surgeryWindow": "다음달",
            "visitSchedule": "다음주 금요일",
            "procedurePlan": "자가조직 재건",
        },
    }

    visited = walk_scenario(engine, "revisionFatigue", "scenRevision", slot_feeder, "P5 보형물없음")

    expected = [
        "p5Collect", "p5AskLifestyle", "p5AskDetail",
        "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona5_with_implant(engine: FlowEngine):
    """P5: 보형물 있음 → implantCondition/Hospital 필수, STANDARD"""
    slot_feeder = {
        "p5Collect": {
            "bodyInfo": "163cm 52kg",
            "bodyFat": "20",
            "bodyType": "마른편",
        },
        "p5AskLifestyle": {
            "activityPattern": "주2회 필라테스",
            "smoking": "false",
            "workConstraint": "프리랜서",
            "recoveryAllowance": "3주",
        },
        "p5AskDetail": {
            "breastCancerHistory": "false",
            "implantPresence": "true",        # 보형물 있음
            "cancerSurgeryType": "해당없음",
            "fatSourceAvailability": "허벅지",
            "pastOps": "가슴 확대 2회",
            "pastOpsSite": "가슴",
        },
        "p5AskMedical": {
            "implantCondition": "구축",        # 보형물 있으므로 수집 필수
            "implantOriginHospital": "A성형외과",  # 보형물 있으므로 수집 필수
        },
        # p5InformSurgery: ruleCancerNone → STANDARD
        "p5InformInfo": {
            "aftercarePlan": "주기적 초음파 검사",
            "scarManagement": "레이저 치료",
            "riskExplanationLevel": "상세",
        },
        "p5Confirm": {
            "customerName": "노은지",
            "phoneNumber": "010-1212-3434",
            "surgeryWindow": "2개월 후",
            "visitSchedule": "다음주 월요일",
            "procedurePlan": "보형물 교체 + 자가지방 이식",
        },
    }

    visited = walk_scenario(engine, "revisionFatigue", "scenRevision", slot_feeder, "P5 보형물있음")

    expected = [
        "p5Collect", "p5AskLifestyle", "p5AskDetail",
        "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona5_conditional_walk(engine: FlowEngine):
    """P5: 유방암+부분절제 → CONDITIONAL 전체 플로우"""
    slot_feeder = {
        "p5Collect": {
            "bodyInfo": "155cm 52kg",
            "bodyFat": "22",
            "bodyType": "마른편",
        },
        "p5AskLifestyle": {
            "activityPattern": "산책 위주",
            "smoking": "false",
            "workConstraint": "사무직",
            "recoveryAllowance": "4주",
        },
        "p5AskDetail": {
            "breastCancerHistory": "true",
            "implantPresence": "false",
            "cancerSurgeryType": "부분",
            "fatSourceAvailability": "허벅지",
            "pastOps": "유방 재건 1회",
            "pastOpsSite": "가슴",
        },
        "p5AskMedical": {
            # implantPresence=false → implantCondition, implantOriginHospital 스킵
        },
        # p5InformSurgery: ruleCancerConditional → CONDITIONAL
        "p5InformInfo": {
            "aftercarePlan": "주치의 협진",
            "scarManagement": "실리콘 시트",
            "riskExplanationLevel": "상세",
        },
        "p5Confirm": {
            "customerName": "오수연",
            "phoneNumber": "010-5656-7878",
            "surgeryWindow": "3개월 후",
            "visitSchedule": "다음주 목요일",
            "procedurePlan": "자가조직 재건",
        },
    }

    visited = walk_scenario(engine, "revisionFatigue", "scenRevision", slot_feeder, "P5 CONDITIONAL")

    expected = [
        "p5Collect", "p5AskLifestyle", "p5AskDetail",
        "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona5_not_allowed_walk(engine: FlowEngine):
    """P5: 유방암+전절제 → NOT_ALLOWED 전체 플로우"""
    slot_feeder = {
        "p5Collect": {
            "bodyInfo": "157cm 50kg",
            "bodyFat": "20",
            "bodyType": "마른편",
        },
        "p5AskLifestyle": {
            "activityPattern": "거의 안함",
            "smoking": "false",
            "workConstraint": "주부",
            "recoveryAllowance": "2주",
        },
        "p5AskDetail": {
            "breastCancerHistory": "true",
            "implantPresence": "true",
            "cancerSurgeryType": "완전",
            "fatSourceAvailability": "복부",
            "pastOps": "가슴 수술 3회",
            "pastOpsSite": "가슴",
        },
        "p5AskMedical": {
            "implantCondition": "파손",
            "implantOriginHospital": "B성형외과",
        },
        # p5InformSurgery: ruleCancerNotAllowed → NOT_ALLOWED
        "p5InformInfo": {
            "aftercarePlan": "종합 사후관리",
            "scarManagement": "레이저 흉터 치료",
            "riskExplanationLevel": "상세",
        },
        "p5Confirm": {
            "customerName": "임소정",
            "phoneNumber": "010-9090-1010",
            "surgeryWindow": "상담 후 결정",
            "visitSchedule": "다음주 월요일",
            "procedurePlan": "대안 시술 상담",
        },
    }

    visited = walk_scenario(engine, "revisionFatigue", "scenRevision", slot_feeder, "P5 NOT_ALLOWED")

    expected = [
        "p5Collect", "p5AskLifestyle", "p5AskDetail",
        "p5AskMedical", "p5InformSurgery", "p5InformInfo", "p5Confirm",
    ]
    assert visited == expected, f"경로 불일치: {visited} != {expected}"

    return True


def test_persona5_implant_skip_logic(engine: FlowEngine):
    """P5: implantPresence=false → implantCondition, implantOriginHospital 스킵 확인"""
    state = make_state("revisionFatigue", "scenRevision", "p5AskMedical", {
        "implantPresence": "false",
    })
    assert engine.should_skip_check_item("implantCondition", state) == True
    assert engine.should_skip_check_item("implantOriginHospital", state) == True

    # implantPresence=true → 스킵 안 됨
    state2 = make_state("revisionFatigue", "scenRevision", "p5AskMedical", {
        "implantPresence": "true",
    })
    assert engine.should_skip_check_item("implantCondition", state2) == False
    assert engine.should_skip_check_item("implantOriginHospital", state2) == False

    return True


def test_persona5_cancer_not_skipped(engine: FlowEngine):
    """P5: cancerSurgeryType은 breastCancerHistory=false여도 스킵하지 않음
    (cancerSurgeryType은 p5AskDetail의 CheckItem이므로 해당 Step에서 테스트)"""
    state = make_state("revisionFatigue", "scenRevision", "p5AskDetail", {
        "breastCancerHistory": "false",
    })
    assert engine.should_skip_check_item("cancerSurgeryType", state) == False

    return True


def test_persona5_branching_cancer_none(engine: FlowEngine):
    """P5: breastCancerHistory=false → ruleCancerNone → STANDARD"""
    state = make_state("revisionFatigue", "scenRevision", "p5AskMedical", {
        # p5AskDetail에서 수집된 슬롯 (이전 Step에서 이미 채워짐)
        "breastCancerHistory": "false",
        "implantPresence": "false",
        "cancerSurgeryType": "해당없음",
        # p5AskMedical의 CheckItem들
        "fatSourceAvailability": "복부",
        "pastOps": "1회",
        "pastOpsSite": "가슴",
    })

    transition = engine.next_step(state)
    assert transition.via == "branching", f"Expected branching, got {transition.via}"
    assert transition.protocol_mode == "STANDARD", f"Expected STANDARD, got {transition.protocol_mode}"

    return True


def test_persona5_branching_cancer_conditional(engine: FlowEngine):
    """P5: breastCancerHistory=true + cancerSurgeryType=부분 → CONDITIONAL"""
    state = make_state("revisionFatigue", "scenRevision", "p5AskMedical", {
        # p5AskDetail에서 수집된 슬롯
        "breastCancerHistory": "true",
        "cancerSurgeryType": "부분",
        "implantPresence": "false",
        # p5AskMedical의 CheckItem들
        "fatSourceAvailability": "복부",
        "pastOps": "1회",
        "pastOpsSite": "가슴",
    })

    transition = engine.next_step(state)
    assert transition.via == "branching", f"Expected branching, got {transition.via}"
    assert transition.protocol_mode == "CONDITIONAL", f"Expected CONDITIONAL, got {transition.protocol_mode}"

    return True


def test_persona5_branching_cancer_not_allowed(engine: FlowEngine):
    """P5: breastCancerHistory=true + cancerSurgeryType=완전 → NOT_ALLOWED"""
    state = make_state("revisionFatigue", "scenRevision", "p5AskMedical", {
        # p5AskDetail에서 수집된 슬롯
        "breastCancerHistory": "true",
        "cancerSurgeryType": "완전",
        "implantPresence": "true",
        # p5AskMedical의 CheckItem들
        "fatSourceAvailability": "복부",
        "implantCondition": "파손",
        "implantOriginHospital": "B성형외과",
        "pastOps": "1회",
        "pastOpsSite": "가슴",
    })

    transition = engine.next_step(state)
    assert transition.via == "branching", f"Expected branching, got {transition.via}"
    assert transition.protocol_mode == "NOT_ALLOWED", f"Expected NOT_ALLOWED, got {transition.protocol_mode}"

    return True


# ===========================================================================
# protocolMode 시스템 관리 테스트
# ===========================================================================

def test_protocol_mode_always_skipped(engine: FlowEngine):
    """protocolMode는 어떤 상태에서든 항상 스킵 (물어보면 안 됨)"""
    empty_state = make_state("slimBody", "scenLowFat", "p1CollectInfo")
    assert engine.should_skip_check_item("protocolMode", empty_state) == True

    filled_state = make_state("longDistance", "scenRemote", "p4Collect", {
        "protocolMode": "FULL",
    })
    assert engine.should_skip_check_item("protocolMode", filled_state) == True

    return True


# ===========================================================================
# 실행
# ===========================================================================

def run_all_tests():
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    engine = FlowEngine(driver)

    tests = [
        # Persona 1: slimBody
        ("P1-STANDARD", test_persona1_standard),
        ("P1-LOWFAT", test_persona1_lowfat),
        ("P1-SKIP-PASTOPSSITE", test_persona1_skip_pastopssite),
        ("P1-SKIP-WEIGHTGAIN", test_persona1_skip_weightgain),

        # Persona 2: lipoCustomer
        ("P2-LIPO-ONLY", test_persona2_lipo_only),
        ("P2-LIPO+TRANSFER", test_persona2_lipo_plus_transfer),
        ("P2-STEMCELL", test_persona2_stemcell_transfer),

        # Persona 3: skinTreatment
        ("P3-FULL", test_persona3_full),

        # Persona 4: longDistance
        ("P4-ABROAD", test_persona4_abroad),
        ("P4-SEMIREMOTE", test_persona4_semiremote),
        ("P4-STANDARD", test_persona4_standard),
        ("P4-REGION-AUTOCALC", test_persona4_region_autocalc),
        ("P4-INBODY-SKIP", test_persona4_inbody_skip),

        # Persona 5: revisionFatigue
        ("P5-NO-CANCER-NO-IMPLANT", test_persona5_no_cancer_no_implant),
        ("P5-WITH-IMPLANT", test_persona5_with_implant),
        ("P5-CONDITIONAL-WALK", test_persona5_conditional_walk),
        ("P5-NOT-ALLOWED-WALK", test_persona5_not_allowed_walk),
        ("P5-IMPLANT-SKIP", test_persona5_implant_skip_logic),
        ("P5-CANCER-NOT-SKIPPED", test_persona5_cancer_not_skipped),
        ("P5-BRANCH-CANCER-NONE", test_persona5_branching_cancer_none),
        ("P5-BRANCH-CANCER-CONDITIONAL", test_persona5_branching_cancer_conditional),
        ("P5-BRANCH-CANCER-NOT-ALLOWED", test_persona5_branching_cancer_not_allowed),

        # 공통
        ("PROTOCOL-MODE-SKIP", test_protocol_mode_always_skipped),
    ]

    passed = 0
    failed = 0
    errors = []

    print("=" * 70)
    print(f"  SC301 페르소나별 플로우 테스트 ({len(tests)}건)")
    print("=" * 70)
    print()

    for name, test_fn in tests:
        engine.clear_cache()  # 테스트 간 캐시 격리
        try:
            result = test_fn(engine)
            if result:
                print(f"  {PASS} {name}")
                passed += 1
            else:
                print(f"  {FAIL} {name} - returned False")
                failed += 1
                errors.append((name, "returned False"))
        except AssertionError as e:
            print(f"  {FAIL} {name} - {e}")
            failed += 1
            errors.append((name, str(e)))
        except Exception as e:
            print(f"  {FAIL} {name} - ERROR: {type(e).__name__}: {e}")
            failed += 1
            errors.append((name, f"{type(e).__name__}: {e}"))

    print()
    print("-" * 70)
    print(f"  결과: {passed} passed, {failed} failed (총 {len(tests)}건)")
    print("-" * 70)

    if errors:
        print()
        print("  실패 상세:")
        for name, err in errors:
            print(f"    {FAIL} {name}: {err}")

    driver.close()

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
