"""
test_persona_identification.py - 페르소나 식별 정확도 테스트

판단기준 문서(_SC301_Persona_판단기준정리_260220.xlsx)의 식별 신호·판별 포인트 기반으로
_infer_persona() 키워드 매칭이 올바른 페르소나를 반환하는지 검증합니다.

Neo4j 불필요 — 키워드 매칭 로직만 단독 테스트.

테스트 레이어:
  Layer 1: Positive 식별 테스트 (초기 발화 → 올바른 persona_id)
  Layer 2: Disambiguation 트리거 테스트 (모호한 발화 → 점수 동점 확인)
  Layer 3: Disambiguation 해소 테스트 (원본+답변 합산 → 올바른 persona_id)
  Layer 4: Negative/경계 테스트 (유사 발화 → 특정 persona가 아닌지 확인)

사용법:
  python test_persona_identification.py              # 전체 실행
  python test_persona_identification.py --verbose    # 상세 로그
  python test_persona_identification.py --persona P1 # 특정 페르소나만
"""

from __future__ import annotations

import argparse
import sys

from flow import FlowEngine

# =============================================================================
# ANSI 컬러
# =============================================================================
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    DIM     = "\033[2m"

def ok(text):    return f"{C.GREEN}{text}{C.RESET}"
def err(text):   return f"{C.RED}{text}{C.RESET}"
def warn(text):  return f"{C.YELLOW}{text}{C.RESET}"
def dim(text):   return f"{C.DIM}{text}{C.RESET}"

# =============================================================================
# 전체 페르소나 목록 (테스트용 mock)
# =============================================================================
ALL_PERSONAS = [
    {"personaId": "slimBody"},
    {"personaId": "lipoCustomer"},
    {"personaId": "skinTreatment"},
    {"personaId": "longDistance"},
    {"personaId": "revisionFatigue"},
]

# =============================================================================
# Layer 1: Positive 식별 테스트
# (utterance, expected_persona, description)
#
# 출처: 엑셀 판단기준 문서의
#   - 핵심 판단 기준 (§X.2)
#   - 식별 신호 유형 (§X.6)
#   - 판별 포인트 (§X.6)
#   - 식별 프로세스 내 예시 질문 (§X.5) 기반 발화
# =============================================================================
POSITIVE_TESTS: list[tuple[str, str, str]] = [

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # P1 슬림바디고민러 (slimBody)
    # 핵심: 지방이식 관심 + 체지방 부족 우려 + 배경(운동/출산/트랜스)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 식별 신호: 지방이식 + 채취 부족 직접형
    ("지방이식을 하고 싶은데 마른 편이라 채취할 지방이 충분할까요?",
     "slimBody", "P1-01 직접형: 지방이식+마른+채취부족"),

    ("체지방률이 낮은데 수술이 가능할까요?",
     "slimBody", "P1-02 직접형: 체지방률+가능 여부"),

    ("지방이 충분할까요? 뺄 데가 없어서 걱정이에요.",
     "slimBody", "P1-03 직접형: 뺄데없음+채취 우려"),

    # 식별 신호: 배경 결합형 (운동)
    ("운동을 많이 해서 체지방이 낮은데 지방이식이 가능한지 궁금해요.",
     "slimBody", "P1-04 배경결합형-운동: 체지방낮음+지방이식"),

    ("바디프로필 준비 중인데 체지방률이 낮아서 지방이식 가능할까요?",
     "slimBody", "P1-05 배경-운동선수: 바디프로필+체지방률"),

    ("보디빌딩 대회 준비하면서 체지방 관리하고 있는데, 시즌 끝나고 지방이식 받고 싶어요.",
     "slimBody", "P1-06 배경-보디빌딩: 대회+체지방관리+지방이식"),

    # 식별 신호: 배경 결합형 (출산)
    ("출산 후 체형 변화가 심해서 지방이식으로 복원하고 싶은데 살이 너무 빠졌어요.",
     "slimBody", "P1-07 배경-출산: 산후+지방이식+살빠짐"),

    ("산후 다이어트를 했더니 체지방이 너무 적어져서 가슴에 지방이식 가능한지 궁금해요.",
     "slimBody", "P1-08 배경-산후: 산후다이어트+체지방적음+지방이식"),

    # 식별 신호: 배경 결합형 (트랜스젠더)
    ("트랜스젠더인데 호르몬 치료 중이에요. 지방이식으로 체형 보정이 가능할까요?",
     "slimBody", "P1-09 배경-트랜스: 호르몬치료+지방이식+체형"),

    ("HRT 받고 있는데 체지방이 적어서 지방이식이 될지 모르겠어요.",
     "slimBody", "P1-10 배경-HRT: 호르몬+체지방적음"),

    # 식별 신호: 증량 의사 + 방법형
    ("필요하면 살을 좀 찌워서 지방이식할 의향이 있는데, 얼마나 어떻게 증량해야 하나요?",
     "slimBody", "P1-11 증량의사형: 살찌우기+지방이식+증량방법"),

    ("체지방률을 몇%까지 높여야 지방이식이 가능한가요?",
     "slimBody", "P1-12 증량의사형: 체지방률+기준치 문의"),

    # 판별 포인트: 재료(지방) 인지 → "가능해요? 지방이 있어요?"
    ("복부는 지방이 없고 허벅지도 별로인데… 채취할 곳이 있을까요?",
     "slimBody", "P1-13 채취부위구체적: 복부없음+허벅지+채취"),

    # 판별 포인트: 대안 탐색
    ("지방이 부족하면 다른 방법은 뭐가 있나요? 대안이 궁금해요.",
     "slimBody", "P1-14 대안탐색: 지방부족+대안"),

    # 판별 포인트: 시간/준비 계획 (증량 의사)
    ("수술 전에 체중을 늘려야 하나요? 언제부터 준비해야 해요?",
     "slimBody", "P1-15 준비계획: 체중늘리기+수술전준비"),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # P2 지방흡입 후 이식타입 (lipoCustomer)
    # 핵심: 흡입+이식 복합, 효과시점/부작용/비용 3종세트, 방식 비교, 빠른 예약
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 식별 신호: 복합 시술 + 핵심 우선순위
    ("지방흡입하고 그 지방으로 이식하는 걸 생각 중인데, 효과가 언제부터 보이고 부작용 위험은 어떤가요?",
     "lipoCustomer", "P2-01 복합+우선순위: 흡입+이식+효과시점+부작용"),

    ("지방흡입해서 빼고 그 지방으로 채우는 시술이 있다고 들었는데, 회복기간이 얼마나 걸리나요?",
     "lipoCustomer", "P2-02 복합: 흡입+빼고채우는+회복"),

    # 식별 신호: 비교 요구 (핵심 트리거)
    ("일반 지방이식이랑 줄기세포 지방이식은 차이가 정확히 뭐예요?",
     "lipoCustomer", "P2-03 방식비교: 일반 vs 줄기세포"),

    ("가격 차이만큼 효과 차이가 있나요? 일반이랑 줄기세포 장단점을 알고 싶어요.",
     "lipoCustomer", "P2-04 방식비교+가성비: 가격차이+효과차이+장단점"),

    # 식별 신호: 정보 탐색 + 빠른 예약 의지
    ("대략 비교만 되면 바로 상담 예약하고 싶어요.",
     "lipoCustomer", "P2-05 빠른예약: 비교+바로상담"),

    ("여러 군데 비교 중인데, 이번 달 안에 결정하려고요. 빨리 진행 가능해요?",
     "lipoCustomer", "P2-06 빠른예약: 여러곳비교+이번달+빨리진행"),

    # SVF 직접 언급 = 강한 신호
    ("SVF 줄기세포 지방이식 비용이 얼마나 하나요? 가성비가 괜찮은지 궁금해요.",
     "lipoCustomer", "P2-07 SVF직접언급: 줄기세포+가성비"),

    # 판별 포인트: 3종 세트 질문
    ("효과는 언제부터 보이고, 부작용 위험은 어떻고, 비용 대비 만족도는 어때요?",
     "lipoCustomer", "P2-08 3종세트: 효과시점+부작용+비용대비"),

    # 판별 포인트: 프로세스 질문 비중 높음
    ("지방흡입 수술 과정이 어떻게 되나요? 회복기간이랑 단계별 주의사항이 궁금해요.",
     "lipoCustomer", "P2-09 프로세스: 흡입+과정+회복+주의사항"),

    # 판별 포인트: 복부 흡입 단독 관심
    ("복부 지방흡입만 하고 싶어요. 람스 시술이 효과적인가요?",
     "lipoCustomer", "P2-10 흡입단독: 복부+지방흡입+람스"),

    # 바디라인 + 흡입
    ("바디라인 정리하려고 지방흡입 알아보고 있어요. 옆구리랑 허벅지요.",
     "lipoCustomer", "P2-11 바디라인: 라인정리+지방흡입"),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # P3 피부시술 고민러 (skinTreatment)
    # 핵심: 팔자/볼꺼짐/동안, 자연+유지, 안전/회복 우선, 기존 경험, 쉬운 설명
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 식별 신호: 부위+자연스러움+유지
    ("팔자주름이랑 볼 꺼짐이 고민인데, 한 번 해도 자연스럽게 오래 유지되는 방법이 있을까요?",
     "skinTreatment", "P3-01 부위+자연+유지: 팔자+볼꺼짐+오래유지"),

    ("볼살이 빠져서 나이 들어 보여요. 동안 느낌으로 자연스럽게 볼륨 채울 수 있나요?",
     "skinTreatment", "P3-02 동안+자연: 볼살+나이들어보임+동안"),

    # 식별 신호: 안전/회복 최우선
    ("무엇보다 안전한지랑 회복기간이 얼마나 걸리는지가 제일 궁금해요.",
     "skinTreatment", "P3-03 안전우선: 안전+회복기간"),

    ("부작용이랑 통증이 걱정돼요. 시술 후 며칠이면 출근할 수 있어요?",
     "skinTreatment", "P3-04 안전우선: 부작용+통증+일상복귀"),

    # 식별 신호: 필러/보톡스 경험 + 쉬운 설명 요청
    ("필러나 보톡스는 해봤는데, 다른 방법은 차이를 잘 모르겠어요. 쉽게 비교해주실 수 있나요?",
     "skinTreatment", "P3-05 경험+설명요청: 필러해봤+차이+쉽게"),

    ("보톡스 해봤는데 효과가 금방 빠졌어요. 더 오래 유지되는 방법 없을까요?",
     "skinTreatment", "P3-06 경험+유지: 보톡스해봤+효과빠짐+오래유지"),

    # 동안 + 주름
    ("동안 느낌으로 자연스럽게 해주는 시술이 뭐가 있을까요? 주름이 신경 쓰여요.",
     "skinTreatment", "P3-07 동안+주름: 자연스럽게+주름"),

    # 판별 포인트: '자연+유지'가 먼저 (효과 크기보다)
    ("피부 시술 한 번으로 티 안 나게 자연스럽고 오래 유지됐으면 좋겠어요.",
     "skinTreatment", "P3-08 자연+유지: 피부시술+자연+오래유지"),

    # 판별 포인트: 안전/회복 초반 3턴 이내
    ("얼굴에 시술 받고 싶은데 붓기랑 멍이 얼마나 가요? 일상생활에 지장 없을까요?",
     "skinTreatment", "P3-09 회복초반: 붓기+멍+일상생활"),

    # 판별 포인트: 이미 경험한 시술이 기준점
    ("예전에 필러 맞았을 때 효과가 3개월밖에 안 갔거든요. 더 지속되는 시술이 있나요?",
     "skinTreatment", "P3-10 경험기준: 필러경험+지속성"),

    # 판별 포인트: 재방문/반복 시술 부담
    ("자주 받기는 부담이에요. 한 번에 오래 유지되는 시술이 뭐가 있을까요?",
     "skinTreatment", "P3-11 반복부담: 자주받기부담+한번에+오래유지"),

    # 팔자주름 단독
    ("팔자주름이 깊어지는 게 고민이에요. 어떤 시술이 좋은가요?",
     "skinTreatment", "P3-12 팔자단독: 팔자주름"),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # P4 원거리 거주자 (longDistance)
    # 핵심: 해외/원거리 거주 + 일정 제약 + 내원 횟수 + 회복↔이동
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 식별 신호: 해외 체류 + 일정 제약
    ("캐나다 토론토에서 유학 중인데 한국에 잠깐 들어갈 때 지방이식을 하려고 해요. 내원은 보통 몇 번 해야 하나요?",
     "longDistance", "P4-01 해외+일정: 캐나다+유학+내원횟수"),

    ("미국에 살고 있어요. 한국 방문 기간에 맞춰서 시술 가능한가요?",
     "longDistance", "P4-02 해외+일정: 미국+방문기간"),

    ("일본에서 왔는데 체류 기간이 짧아서요. 당일 상담하고 시술까지 가능할까요?",
     "longDistance", "P4-03 해외+당일: 일본+체류기간짧음+당일"),

    # 식별 신호: 회복/이동 가능 시점 우선
    ("출국 일정이 있어서요. 시술 후 며칠 정도면 비행기 타는 게 가능한가요?",
     "longDistance", "P4-04 회복+이동: 출국+비행기"),

    ("해외에서 오는데 장거리 비행 전에 어느 정도까지 회복이 되어야 하나요?",
     "longDistance", "P4-05 회복+이동: 해외+장거리비행+회복"),

    # 체류 기간 + 당일 진행
    ("체류 기간이 7일인데 당일 상담하고 바로 시술까지 가능한가요?",
     "longDistance", "P4-06 시간관리형: 체류기간+당일"),

    ("한국에 10일 있을 수 있어요. 검사 포함해서 총 몇 번 내원해야 해요?",
     "longDistance", "P4-07 시간관리형: 체류10일+내원횟수"),

    # 국내 원거리
    ("제주도에서 사는데 서울까지 가야 하나요? 내원 횟수를 최소화하고 싶어요.",
     "longDistance", "P4-08 국내원거리: 제주+내원횟수최소"),

    ("부산에서 가야 하는데 원거리 상담 프로그램이 있다고 들었어요.",
     "longDistance", "P4-09 국내원거리: 부산+원거리상담"),

    # 판별 포인트: 일정 가능성이 먼저
    ("몇 번 가야 해요? 검사 포함이에요? 경과 체크는 언제 해요?",
     "longDistance", "P4-10 내원횟수반복: 횟수+검사+경과체크"),

    # 판별 포인트: 제약 조건이 구체적
    ("해외에서 들어가는데 한국에 5일밖에 못 있어요. 주말 포함해서 시술 가능한 일정이 있나요?",
     "longDistance", "P4-11 구체적제약: 해외+5일+주말포함"),

    # 판별 포인트: 비용보다 시간 효율
    ("해외에서 잠깐 들어가는 거라 비용은 괜찮아요. 체류 기간 내에 맞는 플랜이 가능해야 해요.",
     "longDistance", "P4-12 시간효율: 해외+체류기간+일정맞춤"),

    # 판별 포인트: 회복과 이동 연결
    ("회복이 언제쯤 되면 장거리 이동 가능해요? 출국 전에 어느 정도까지 안정화돼야 하나요?",
     "longDistance", "P4-13 회복+이동연결: 장거리이동+출국전+안정화"),

    # 해외번호/시차 언급
    ("해외번호로 연락 가능한가요? 시차가 있어서 전화 상담 시간이 제한적이에요.",
     "longDistance", "P4-14 해외번호: 해외번호+시차"),

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # P5 재수술에 지친 마음 (revisionFatigue)
    # 핵심: 과거 가슴 수술 이력 + 이물감/촉감 + 제거/교체 + 리스크 민감 + 원스텝
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 식별 신호: 과거 수술 + 이물감/자연스러움 + 재수술
    ("4년 전에 가슴 수술했는데 자연스럽지 않고 이물감이 있어서 재수술을 고민 중이에요.",
     "revisionFatigue", "P5-01 재수술+이물감: 과거수술+이물감+재수술"),

    ("몇 년 전에 보형물 넣었는데 딱딱한 느낌이 나서 너무 불편해요.",
     "revisionFatigue", "P5-02 촉감불만: 보형물+딱딱함+불편"),

    # 식별 신호: 완전 제거 + 자연 촉감
    ("보형물 완전 제거하고 자연스럽게 만들 수 있을까요? 흉터도 최대한 티 안 나게요.",
     "revisionFatigue", "P5-03 제거+자연+흉터: 완전제거+자연+비노출"),

    ("보형물 빼고 싶어요. 제거 후에는 어떻게 돼요?",
     "revisionFatigue", "P5-04 제거의도: 보형물+빼고싶다"),

    # 식별 신호: 리스크 민감 + 원스텝
    ("석회화나 괴사 같은 위험이 걱정돼요. 가능하면 한 번에 끝낼 수 있는 방법이 있을까요?",
     "revisionFatigue", "P5-05 리스크+원스텝: 석회화+괴사+한번에끝"),

    ("구형구축이 온 것 같은데 재수술하면 또 위험한 건 아닌가요?",
     "revisionFatigue", "P5-06 리스크민감: 구형구축+재수술+위험"),

    # 구형구축 + 보형물
    ("구형구축이 와서 보형물을 빼고 싶은데, 재수술 후 촉감은 어떻게 되나요?",
     "revisionFatigue", "P5-07 구형구축+제거: 보형물+재수술+촉감"),

    # 판별 포인트: 촉감/이물감 반복
    ("만졌을 때 딱딱하고 이물감이 느껴져요. 자연스러운 촉감으로 바꿀 수 있나요?",
     "revisionFatigue", "P5-08 촉감반복: 딱딱함+이물감+자연촉감"),

    # 판별 포인트: 합병증 단어가 구체적
    ("피막이 두꺼워진 것 같아요. 캡슐렉토미가 필요한가요?",
     "revisionFatigue", "P5-09 합병증구체적: 피막+캡슐렉토미"),

    # 판별 포인트: 원스텝 집착
    ("재수술을 두 번이나 하는 건 부담돼요. 보형물 제거하고 한번에 끝낼 수 있을까요?",
     "revisionFatigue", "P5-10 원스텝집착: 재수술+두번부담+보형물제거+한번에"),

    # 판별 포인트: 비대칭/사이즈 재설정까지 질문
    ("좌우 비대칭도 교정하고 사이즈도 줄이고 싶어요. 보형물 제거 후에 가능한가요?",
     "revisionFatigue", "P5-11 비대칭+사이즈: 비대칭+사이즈줄이기+제거"),

    # 판별 포인트: '확대'가 아닌 '제거+자연스러움 회복'
    ("더 키우고 싶은 게 아니라 지금 있는 보형물을 빼고 자연스럽게 돌아가고 싶어요.",
     "revisionFatigue", "P5-12 제거+자연회복: 보형물+빼고+자연스럽게"),

    # 심리적 거부감
    ("보형물 때문에 심리적으로 거부감이 있어요. 제거하면 자연스러워질까요?",
     "revisionFatigue", "P5-13 심리적거부: 보형물+심리적거부+제거"),

    # 유방암 + 재건 상담
    ("유방암 수술 후에 재건 상담을 받고 싶어요. 이전 수술 이력이 있어서요.",
     "revisionFatigue", "P5-14 유방암재건: 이전수술+재건"),
]

# =============================================================================
# Layer 2: Disambiguation 트리거 테스트
# (utterance, expected_top2_set, should_disambiguate, description)
#
# _score_personas() 결과로 모호성 감지가 올바르게 작동하는지 검증.
# should_disambiguate=True: 상위 2개 점수차 ≤ THRESHOLD → 확인 질문 필요
# should_disambiguate=False: 점수차 > THRESHOLD → 즉시 확정
# =============================================================================
DISAMBIGUATION_TRIGGER_TESTS: list[tuple[str, set[str], bool, str]] = [

    # ── 모호: P1 vs P2 동점 → disambiguation 트리거 ──────────────────
    ("지방이식 가능한지 궁금해요.",
     {"slimBody", "lipoCustomer"}, True,
     "DISAM-01: 지방이식 단독, P1=P2 동점"),

    ("지방이식으로 얼마나 커질 수 있나요?",
     {"slimBody", "lipoCustomer"}, True,
     "DISAM-02: 지방이식+결과 질문, P1=P2 동점"),

    ("가슴 지방이식 하고 싶어요.",
     {"slimBody", "lipoCustomer"}, True,
     "DISAM-03: 가슴+지방이식, P1=P2 동점"),

    # ── 명확: disambiguation 불필요 ──────────────────────────────────
    ("줄기세포 지방이식 상담받고 싶어요.",
     {"lipoCustomer"}, False,
     "DISAM-04: 줄기세포 → P2 명확"),

    ("마른 편인데 지방이식 가능한가요?",
     {"slimBody"}, False,
     "DISAM-05: 마른+지방이식 → P1 명확"),

    ("지방흡입하고 이식하려고요.",
     {"lipoCustomer"}, False,
     "DISAM-06: 흡입+이식 → P2 명확"),
]

# =============================================================================
# Layer 3: Disambiguation 해소 테스트
# (original_text, answer_text, expected_persona, description)
#
# 원본 텍스트 + 답변 합산 후 _infer_persona()가 올바른 페르소나를 반환하는지 검증.
# =============================================================================
DISAMBIGUATION_RESOLUTION_TESTS: list[tuple[str, str, str, str]] = [

    # ── P1 방향 해소 ────────────────────────────────────────────────
    ("가슴 지방이식 하고 싶어요",
     "좀 마른 편이에요, 지방이 충분할지 걱정돼요",
     "slimBody",
     "RESOLVE-01: P1 방향 (마른+지방부족)"),

    ("지방이식 가능한지 궁금해요",
     "체지방이 적어서 채취할 곳이 걱정이에요",
     "slimBody",
     "RESOLVE-02: P1 방향 (체지방+채취걱정)"),

    # ── P2 방향 해소 ────────────────────────────────────────────────
    ("가슴 지방이식 하고 싶어요",
     "지방흡입하고 그 지방으로 이식하는 거요",
     "lipoCustomer",
     "RESOLVE-03: P2 방향 (흡입+이식 복합)"),

    ("가슴 지방이식 하고 싶어요",
     "줄기세포 방식이랑 일반 방식 비교가 궁금해요",
     "lipoCustomer",
     "RESOLVE-04: P2 방향 (줄기세포 비교)"),
]

# =============================================================================
# Layer 4: Negative/경계 테스트
# (utterance, NOT_expected_persona, description)
# 해당 발화가 NOT_expected_persona로 분류되면 안 됨
# =============================================================================
NEGATIVE_TESTS: list[tuple[str, str, str]] = [

    # ── P1 vs P2 경계 ────────────────────────────────────────────────
    # 핵심: P1은 "재료(지방) 부족 인지"가 있어야 함
    # (P1=P2 동점 케이스는 Layer 2 Disambiguation 트리거 테스트로 이동)

    ("얼굴에 지방이식 하고 싶어요. 비용 대비 효과가 궁금해요.",
     "slimBody", "P1 아님: 얼굴부위+비용관심, P2 방향"),

    # ── P2 vs P1 경계 ────────────────────────────────────────────────
    # P1처럼 보이지만 흡입 단독이면 P2
    ("지방흡입만 하고 싶어요. 이식은 안 할 거예요.",
     "slimBody", "P1 아님: 흡입 단독 → P2 방향, 체지방 부족 인지 없음"),

    # ── P4 vs 일반 ────────────────────────────────────────────────────
    # 단순 빠른 예약 ≠ 원거리
    ("지방이식 예약하고 싶어요. 이번 주 가능한가요?",
     "longDistance", "P4 아님: 단순 빠른 예약, 원거리/해외 맥락 없음"),

    # 회복 기간 문의이지만 원거리 아님
    ("지방흡입 하려는데 회복 기간이 얼마나 걸려요?",
     "longDistance", "P4 아님: 회복 기간 문의이지만 원거리/해외 맥락 없음"),

    # ── P5 vs 일반/P1 ────────────────────────────────────────────────
    # P5는 반드시 재수술/과거 수술 이력이 있어야 함
    ("가슴 수술을 처음 하려고요. 자연스러운 느낌이 중요해요.",
     "revisionFatigue", "P5 아님: 첫 수술, 재수술/과거 이력 없음"),

    ("가슴 성형 상담 받고 싶어요. 보형물이랑 지방이식 중에 고민이에요.",
     "revisionFatigue", "P5 아님: 첫 수술 고민, 재수술 아님"),

    # ── P3 vs P5 ──────────────────────────────────────────────────────
    ("얼굴 피부가 처져서 리프팅 상담받고 싶어요.",
     "revisionFatigue", "P5 아님: 단순 피부 처짐(P3), 재수술 맥락 없음"),

    # ── P2 vs P3 ──────────────────────────────────────────────────────
    # 부위가 얼굴이면 P3 방향
    ("얼굴 동안 시술 받고 싶은데 어떤 게 좋을까요?",
     "lipoCustomer", "P2 아님: 얼굴 동안 시술 → P3 방향"),

    # ── P3 vs P2 ──────────────────────────────────────────────────────
    # 흡입 언급이 있으면 P3이 아닐 가능성
    ("복부 지방흡입 후에 피부 탄력이 걱정이에요.",
     "skinTreatment", "P3 아님: 지방흡입 맥락 → P2 방향"),

    # ── P1 vs P4 ──────────────────────────────────────────────────────
    # 해외 + 시술 → P4가 맞지만, "마른"이 있으면 P1과 경쟁
    # 해외 맥락 없이 마른 체형만 → P1
    ("마른 체형이라 지방이식이 걱정돼요. 서울에서 상담 가능한가요?",
     "longDistance", "P4 아님: 서울 거주+마른체형 → P1 방향"),
]


# =============================================================================
# 테스트 실행
# =============================================================================
def run_tests(
    verbose: bool = False,
    persona_filter: str | None = None,
) -> tuple[int, int, list[str]]:
    """전체 테스트 실행. (passed, failed, fail_details) 반환."""
    engine = FlowEngine(driver=None)  # Neo4j 불필요

    # 페르소나 필터 매핑
    filter_map = {
        "P1": "slimBody", "P2": "lipoCustomer", "P3": "skinTreatment",
        "P4": "longDistance", "P5": "revisionFatigue",
    }
    target_persona = filter_map.get(persona_filter.upper()) if persona_filter else None

    passed = 0
    failed = 0
    details: list[str] = []

    # ── Layer 1: Positive 테스트 ─────────────────────────────────────
    pos_tests = POSITIVE_TESTS
    if target_persona:
        pos_tests = [(u, e, d) for u, e, d in pos_tests if e == target_persona]

    print(f"\n{C.BOLD}{C.CYAN}{'='*70}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  Layer 1: Positive 식별 테스트 ({len(pos_tests)}건){C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*70}{C.RESET}\n")

    for utterance, expected, desc in pos_tests:
        result = engine._infer_persona(utterance, ALL_PERSONAS)
        is_pass = result == expected

        if is_pass:
            passed += 1
            status = ok("PASS")
        else:
            failed += 1
            status = err("FAIL")
            details.append(f"[Positive] {desc}: expected={expected}, got={result}")

        if verbose or not is_pass:
            print(f"  {status}  {desc}")
            if verbose:
                print(f"         발화: \"{utterance[:60]}{'...' if len(utterance) > 60 else ''}\"")
                print(f"         기대: {expected}, 결과: {result}")
                print()

    # ── Layer 2: Disambiguation 트리거 테스트 ─────────────────────────
    print(f"\n{C.BOLD}{C.CYAN}{'='*70}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  Layer 2: Disambiguation 트리거 테스트 ({len(DISAMBIGUATION_TRIGGER_TESTS)}건){C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*70}{C.RESET}\n")

    for utterance, expected_top, should_disam, desc in DISAMBIGUATION_TRIGGER_TESTS:
        scores = engine._score_personas(utterance, ALL_PERSONAS)
        top_diff = scores[0]["score"] - scores[1]["score"] if len(scores) >= 2 else 999
        is_ambiguous = (
            len(scores) >= 2
            and scores[0]["score"] > 0
            and top_diff <= engine.PERSONA_AMBIGUITY_THRESHOLD
        )

        if should_disam:
            actual_top = {scores[0]["id"], scores[1]["id"]}
            is_pass = is_ambiguous and actual_top == expected_top
        else:
            is_pass = not is_ambiguous and scores[0]["id"] in expected_top

        if is_pass:
            passed += 1
            status = ok("PASS")
        else:
            failed += 1
            status = err("FAIL")
            if should_disam:
                actual_top = {scores[0]["id"], scores[1]["id"]}
                details.append(
                    f"[Disam-Trigger] {desc}: should trigger, "
                    f"diff={top_diff}, top2={actual_top}"
                )
            else:
                details.append(
                    f"[Disam-Trigger] {desc}: should NOT trigger, "
                    f"diff={top_diff}, winner={scores[0]['id']}"
                )

        if verbose or not is_pass:
            print(f"  {status}  {desc}")
            if verbose:
                print(f"         발화: \"{utterance[:60]}{'...' if len(utterance) > 60 else ''}\"")
                top3 = ", ".join(f"{s['id']}={s['score']}" for s in scores[:3])
                print(f"         스코어: [{top3}]  diff={top_diff}  ambiguous={is_ambiguous}")
                print()

    # ── Layer 3: Disambiguation 해소 테스트 ─────────────────────────
    print(f"\n{C.BOLD}{C.CYAN}{'='*70}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  Layer 3: Disambiguation 해소 테스트 ({len(DISAMBIGUATION_RESOLUTION_TESTS)}건){C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*70}{C.RESET}\n")

    for original, answer, expected, desc in DISAMBIGUATION_RESOLUTION_TESTS:
        combined = original + " " + answer
        result = engine._infer_persona(combined, ALL_PERSONAS)
        is_pass = result == expected

        if is_pass:
            passed += 1
            status = ok("PASS")
        else:
            failed += 1
            status = err("FAIL")
            details.append(f"[Disam-Resolve] {desc}: expected={expected}, got={result}")

        if verbose or not is_pass:
            print(f"  {status}  {desc}")
            if verbose:
                print(f"         원본: \"{original[:50]}\"")
                print(f"         답변: \"{answer[:50]}\"")
                print(f"         기대: {expected}, 결과: {result}")
                print()

    # ── Layer 4: Negative 테스트 ─────────────────────────────────────
    neg_tests = NEGATIVE_TESTS
    if target_persona:
        neg_tests = [(u, n, d) for u, n, d in neg_tests if n == target_persona]

    print(f"\n{C.BOLD}{C.CYAN}{'='*70}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  Layer 4: Negative/경계 테스트 ({len(neg_tests)}건){C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'='*70}{C.RESET}\n")

    for utterance, not_expected, desc in neg_tests:
        result = engine._infer_persona(utterance, ALL_PERSONAS)
        is_pass = result != not_expected

        if is_pass:
            passed += 1
            status = ok("PASS")
        else:
            failed += 1
            status = err("FAIL")
            details.append(f"[Negative] {desc}: should NOT be {not_expected}, got={result}")

        if verbose or not is_pass:
            print(f"  {status}  {desc}")
            if verbose:
                print(f"         발화: \"{utterance[:60]}{'...' if len(utterance) > 60 else ''}\"")
                print(f"         NOT: {not_expected}, 실제: {result}")
                print()

    return passed, failed, details


def main():
    parser = argparse.ArgumentParser(description="페르소나 식별 정확도 테스트")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")
    parser.add_argument("--persona", "-p", type=str, default=None,
                        help="특정 페르소나만 테스트 (P1~P5)")
    args = parser.parse_args()

    print(f"\n{C.BOLD}SC301 페르소나 식별 테스트{C.RESET}")
    filter_info = f" [{args.persona}]" if args.persona else ""
    print(f"{dim(f'판단기준 문서 기반 · Layer 1~4 (Positive/Disam-Trigger/Disam-Resolve/Negative){filter_info}')}\n")

    passed, failed, details = run_tests(verbose=args.verbose, persona_filter=args.persona)
    total = passed + failed

    # ── 결과 요약 ────────────────────────────────────────────────────
    print(f"\n{C.BOLD}{'='*70}{C.RESET}")
    print(f"{C.BOLD}  결과 요약{C.RESET}")
    print(f"{'='*70}")

    # 페르소나별 집계
    engine = FlowEngine(driver=None)
    persona_stats: dict[str, dict[str, int]] = {}
    for utterance, expected, desc in POSITIVE_TESTS:
        if args.persona:
            filter_map = {"P1": "slimBody", "P2": "lipoCustomer", "P3": "skinTreatment",
                          "P4": "longDistance", "P5": "revisionFatigue"}
            if expected != filter_map.get(args.persona.upper()):
                continue
        result = engine._infer_persona(utterance, ALL_PERSONAS)
        persona_stats.setdefault(expected, {"pass": 0, "fail": 0})
        if result == expected:
            persona_stats[expected]["pass"] += 1
        else:
            persona_stats[expected]["fail"] += 1

    print(f"\n  {C.BOLD}Positive 페르소나별:{C.RESET}")
    for pid, stats in sorted(persona_stats.items()):
        p = stats["pass"]
        f = stats["fail"]
        bar = ok(f"{p}P") + (f" {err(f'{f}F')}" if f else "")
        print(f"    {pid:20s} {bar}")

    print(f"\n  전체: {total}건  |  {ok(f'PASS: {passed}')}  |  {err(f'FAIL: {failed}') if failed else dim(f'FAIL: {failed}')}")

    if details:
        print(f"\n{C.BOLD}{C.RED}  실패 상세:{C.RESET}")
        for d in details:
            print(f"    {err('✗')} {d}")

    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
