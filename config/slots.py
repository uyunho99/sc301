"""
config/slots.py - 슬롯 자동계산, 조건부 스킵, 힌트 규칙

AUTO_COMPUTABLE_SLOTS: 다른 슬롯으로부터 자동 계산 가능한 항목
CONDITIONAL_SKIP_RULES: 선행 슬롯에 따라 스킵 가능한 항목
SYSTEM_MANAGED_SLOTS: 시스템이 자동 설정하는 슬롯 목록
CHECKITEM_HINTS: 슬롯별 추출/응답 프롬프트 힌트
REGION_BUCKET_MAP: 국내 지역구 → regionBucket 매핑
"""
from __future__ import annotations

# =============================================================================
# 자동 계산 / 조건부 스킵 규칙
# =============================================================================

# 다른 Slot 값으로부터 자동 계산 가능한 항목
# format: { "계산될_slot": { "requires": [필요한 slot들], "compute": "계산_함수_이름" } }
AUTO_COMPUTABLE_SLOTS = {
    # BMI = 체중(kg) / 키(m)^2  →  bodyInfo에서 키/체중 추출 후 계산
    "bmi": {
        "requires": ["bodyInfo"],
        "compute": "compute_bmi",
        "description": "키/체중 → BMI 자동 계산",
    },
    # regionBucket: 해외면 ABROAD, 국내면 지역구 → S1~S6 매핑
    # requires는 최소한 residenceCountry만 있으면 시도 가능 (ABROAD 판별)
    "regionBucket": {
        "requires": ["residenceCountry"],
        "compute": "compute_region_bucket",
        "description": "거주국/국내지역 → 권역(S1~S6/ABROAD) 자동 매핑",
    },
}

# 선행 Slot 값에 따라 질문을 건너뛸 수 있는 항목
# format: { "스킵될_slot": { "when": { "선행_slot": "조건값" }, "action": "skip" } }
# when의 조건이 모두 만족하면 해당 slot을 스킵 (물어보지 않음)
CONDITIONAL_SKIP_RULES = {
    # NOTE: cancerSurgeryType은 breastCancerHistory=false여도 스킵하지 않음.
    #       유방암 외 다른 암 수술 이력이 있을 수 있으므로 항상 확인.

    # 보형물 없으면 보형물 상태/원래 병원 물을 필요 없음
    "implantCondition": {
        "when": {"implantPresence": "false"},
        "action": "skip",
        "default_value": None,
        "description": "보형물 없으면 보형물 상태 불필요",
    },
    "implantOriginHospital": {
        "when": {"implantPresence": "false"},
        "action": "skip",
        "default_value": None,
        "description": "보형물 없으면 원래 병원 불필요",
    },
    # 해외 거주자에겐 국내 지역구 불필요
    "domesticDistrict": {
        "when": {"residenceCountry": "ABROAD"},
        "action": "skip",
        "default_value": None,
        "description": "해외 거주시 국내 지역구 불필요",
    },
    # 체중 증량 의사 없으면 증량 계획/영양 상담 불필요
    "weightGainPlan": {
        "when": {"weightGainIntent": "false"},
        "action": "skip",
        "default_value": None,
        "description": "체중 증량 의사 없으면 증량 계획 불필요",
    },
    "nutritionConsult": {
        "when": {"weightGainIntent": "false"},
        "action": "skip",
        "default_value": None,
        "description": "체중 증량 의사 없으면 영양 상담 불필요",
    },
    # InBody 데이터 없으면 사진 업로드 요청 불필요
    "inbodyPhotoUpload": {
        "when": {"inbodyAvailable": "false"},
        "action": "skip",
        "default_value": None,
        "description": "InBody 없으면 사진 업로드 불필요",
    },
    # 과거 시술 없으면 시술 부위 물을 필요 없음
    "pastOpsSite": {
        "when": {"pastOps": ["없음", "없습니다", "false", "none", "no", "처음"]},
        "action": "skip",
        "default_value": None,
        "description": "과거 시술 없으면 시술 부위 불필요",
    },
}

# 시스템이 자동 설정하는 Slot (절대 사용자에게 물어보면 안 됨)
SYSTEM_MANAGED_SLOTS = [
    "protocolMode",  # 분기 규칙에 의해 자동 설정
]

# CheckItem 힌트: 추출/응답 프롬프트에서 변수의 의미를 명확히 전달
CHECKITEM_HINTS = {
    # === 공통 신체정보 ===
    "bodyInfo": "키(cm)와 체중(kg)을 함께 기재. 예: '170cm 65kg'",
    "bodyFat": "체지방률(%). 예: '25%'",
    "bodyType": "체형 분류: 마른편 / 보통 / 비만형",
    "inbodyAvailable": "인바디 검사 결과 보유 여부. true 또는 false",
    "inbodyPhotoUpload": "인바디 결과 사진 업로드 여부. true 또는 false",

    # === 공통 시술 이력 ===
    "fatSourceAvailability": "지방 채취 가능 부위 및 지방량. 예: '복부 충분', '허벅지 소량'",
    "pastOps": "과거 수술/시술 이력. 예: '가슴 확대 1회', '가슴 보형물 삽입 1회', '없음'",
    "pastOpsSite": "과거 수술 부위. 예: '가슴', '가슴 좌측', '가슴 양측'",
    "smoking": "흡연 여부. true 또는 false",

    # === P1 슬림바디 ===
    "activityPattern": "일상 활동 패턴. 예: '사무직', '활동적', '운동 자주'",
    "exerciseLevel": "운동 빈도/강도. 예: '주 3회', '거의 안 함'",
    "dietPattern": "식습관/식이 패턴. 예: '저탄고지', '불규칙'",
    "weightGainIntent": "체중 증량 의사. true 또는 false",
    "weightGainPlan": "체중 증량 구체 계획",
    "nutritionConsult": "영양 상담 희망 여부. true 또는 false",
    "concernArea": "관심/고민 부위. 예: '가슴', '가슴 볼륨', '가슴 탄력'",
    "surgeryWindow": "희망 시술 시기. 예: '다음 달', '3개월 내'",
    "recheckSchedule": "재진 일정. 예: '2주 후'",
    "recoveryGuideline": "회복 가이드라인/주의사항. 예: '2주간 압박복 착용', '음주 금지'",

    # === P2 지방흡입 ===
    "basicInfo": "고객 이름과 연락처. 예: '김지현 010-1234-5678'",
    "schedule": "방문 가능 일정",
    "medicalHistory": "과거 병력/수술 이력",
    "upsellAccept": "지방이식 추가 시술 동의. true 또는 false",
    "transferType": "이식 유형 선택: 일반 또는 줄기세포",
    "transferPlanDetail": "이식 세부 계획. 예: '줄기세포 이식 + 가슴 볼륨 보충', '일반 이식 + 가슴 볼륨업'",
    "recoveryAllowance": "회복 가능 기간. 예: '1주일', '2주'",
    "travelConstraint": "이동/방문 제약사항",
    "precheckRequired": "사전검사 필요 여부. true 또는 false",
    "visitSchedule": "방문 예약 일정",
    "sameDayPossible": "당일 시술 가능 여부. true 또는 false",
    "reservationIntent": "예약 의사. true 또는 false",
    "depositReservation": "예약금 결제 의사. true 또는 false",
    "jobIntensity": "직업 강도/활동 수준. 예: '사무직(낮음)', '현장직(높음)', '서비스직(보통)'",
    "lipoArea": "지방흡입 희망 부위 (가슴 이식용 채취). 예: '복부', '허벅지', '옆구리'",
    "lipoGoal": "지방흡입 목표/기대 결과. 예: '가슴 볼륨업', '가슴 지방이식용 채취'",
    "lipoPlanDetail": "흡입 세부 계획. 예: '복부+허벅지 동시 흡입 후 가슴 이식'",
    "riskFactor": "위험 요소/우려사항. 예: '고혈압', '당뇨', '없음'",
    "planPreference": "시술 계획 선호. 예: '한 번에 진행', '단계별 진행'",
    "concernSideEffect": "우려하는 부작용. 예: '울퉁불퉁', '비대칭', '감각 이상'",
    "costSensitivity": "비용 민감도. 예: '예산 중요', '결과 우선', '적절한 선에서'",
    "recoveryTimeline": "회복 일정/기간. 예: '1주 후 출근', '2주 재택'",
    "costRange": "예산 범위. 예: '300만원 이내', '500만원 이내', '제한 없음'",
    "graftExpectation": "이식 기대 효과. 예: '자연스러운 가슴 볼륨', '가슴 탄력 개선'",

    # === P3 피부시술 ===
    "skinType": "피부 타입. 예: '건성', '지성', '복합성', '민감성'",
    "skinCondition": "현재 피부 상태. 예: '가슴 부위 탄력 저하', '수술 후 흉터', '색소침착'",
    "allergyHistory": "알레르기 이력",
    "botoxCycle": "보톡스 시술 주기. 예: '6개월마다', '처음'",
    "fillerHistory": "필러 시술 이력",
    "fillerRemaining": "기존 필러 잔여량/상태. 예: '거의 흡수됨', '일부 남아있음', '없음'",
    "procedurePlan": "시술 계획/선호 시술. 예: '가슴성형 전후 피부관리', '수술 후 피부 탄력 관리'",
    "sunExposure": "자외선 노출 정도. 예: '야외 활동 많음', '실내 위주', '자외선 차단 꾸준히'",
    "skincareRoutine": "스킨케어 루틴. 예: '기초만', '풀코스', '거의 안 함'",
    "desiredEffect": "희망 효과. 예: '가슴 피부 탄력', '수술 후 피부 회복', '흉터 최소화'",
    "durabilityExpectation": "효과 지속 기간 기대. 예: '6개월 이상', '1년', '반영구'",

    # === P4 원거리 ===
    "residenceCountry": "거주국. 예: '한국', '미국', '일본' 또는 '해외'",
    "domesticDistrict": "국내 거주 지역. 예: '서울', '부산', '경기'",
    "regionBucket": "지역 분류 코드 (자동 계산). S1(서울)~S6(강원/제주)",
    "visitPeriod": "한국 방문/체류 기간",
    "aftercarePlan": "시술 후 관리 계획",
    "followupSchedule": "사후 관리 일정",
    "precheckTimeEstimate": "사전검사 소요 시간 예상. 예: '30분', '1시간'",
    "bodyPhotoUpload": "체형 사진 업로드 여부. true 또는 false",
    "documentUpload": "서류(의료기록 등) 업로드 여부. true 또는 false",

    # === P5 재수술 ===
    "breastCancerHistory": "유방암 병력. true 또는 false",
    "cancerSurgeryType": "암 수술 유형: 부분절제 또는 전절제",
    "implantPresence": "보형물 삽입 여부. true 또는 false",
    "implantCondition": "보형물 상태. 예: '양호', '파손', '구축'",
    "implantOriginHospital": "보형물 시술 병원명",
    "revisionReason": "재수술 사유",
    "priorSurgeryCount": "이전 수술 횟수. 예: '1회', '2회'",
    "workConstraint": "직업 제약사항. 예: '2주 후 출근 필수', '재택 가능', '육체 노동'",
    "scarManagement": "흉터 관리 방법. 예: '실리콘 시트', '레이저', '자연 치유'",
    "riskExplanationLevel": "위험성 설명 수준. 예: '상세히', '핵심만', '서면으로'",

    # === 개인정보 (공통 마무리 단계) ===
    "customerName": "고객 성함",
    "phoneNumber": "연락처 (휴대폰 번호). 예: '010-1234-5678'",

    # === 시스템 관리 (참조용) ===
    "protocolMode": "시술 프로토콜 모드 (분기 규칙에 의해 자동 설정)",
}

# 국내 지역구 → regionBucket 매핑 테이블
REGION_BUCKET_MAP = {
    # S1: 서울
    "서울": "S1",
    # S2: 경기
    "경기": "S2", "인천": "S2",
    # S3: 충청/대전/세종
    "대전": "S3", "세종": "S3", "충남": "S3", "충북": "S3", "충청": "S3",
    # S4: 영남/부산/대구/울산
    "부산": "S4", "대구": "S4", "울산": "S4", "경남": "S4", "경북": "S4",
    # S5: 호남/광주/전라
    "광주": "S5", "전남": "S5", "전북": "S5", "전라": "S5",
    # S6: 강원/제주
    "강원": "S6", "제주": "S6",
}
