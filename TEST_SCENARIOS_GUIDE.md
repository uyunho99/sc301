# SC301 테스트 시나리오 전체 가이드

## 파일 구조 및 의존 관계

```
test_repl.py          ← 17개 REPL 시나리오 (TEST_SCENARIOS dict)
  │                      사용자 발화 시뮬레이션, slot 주입/LLM 추출
  │
  ├──► benchmark_scenarios.py   (from test_repl import TEST_SCENARIOS)
  │      성능 벤치마크: 턴별 LLM/Neo4j/벡터검색 시간 측정
  │      InstrumentedCore, InstrumentedFlowEngine 래퍼
  │
  └──► test_scenarios.py        (독립적, TEST_SCENARIOS 미사용)
         23개 단위/통합 테스트 (walk_scenario + assert)
         Neo4j 직접 연결, LLM 없이 slot 직접 주입

공유 의존성:
  flow.py      ← FlowEngine (전이, slot 추출, 응답 생성)
  state.py     ← ConversationState (세션 상태)
  schema.py    ← BRANCHING_RULES, CONDITIONAL_SKIP_RULES,
                  AUTO_COMPUTABLE_SLOTS, SYSTEM_MANAGED_SLOTS
  core.py      ← Core (Neo4j + OpenAI 통합) — benchmark에서만 사용

관련 문서:
  benchmark_analysis.md      V1 리포트 (gpt-5, 23.5초/턴)
  benchmark_analysis_v2.md   V2 리포트 (gpt-4o+mini, 5.8초/턴)
  REPL_SCENARIOS_DETAIL.md   17개 REPL 시나리오 상세 (엑셀 판단기준 커버리지 포함)
  SESSION_CHANGELOG.md       Graph 정합성 검증 & Tier 1 최적화 변경 이력
```

## 실행 방법

```bash
# 단위/통합 테스트 23개 전체 실행 (LLM 불필요, Neo4j 필요)
python test_scenarios.py

# REPL 시뮬레이션 17개 전체 (기본: --no-llm, slot 직접 주입)
python test_repl.py --db local -s all

# 특정 시나리오 REPL (턴마다 일시정지)
python test_repl.py --db local -s p1std --step

# 실제 LLM으로 slot 추출 테스트
python test_repl.py --db local -s p1std --with-llm

# 모델 선택 (gpt-4o / gpt-5)
python test_repl.py --db local -s p1std --with-llm --model gpt-5

# 수동 입력 모드 (직접 타이핑)
python test_repl.py --db local -i

# 벤치마크 (LLM 필수, 전체 시나리오 성능 측정)
python benchmark_scenarios.py --db local
python benchmark_scenarios.py --db local -s p1std --csv result.csv
```

---

## 시나리오 매핑: test_scenarios.py (20개) ↔ test_repl.py (17개)

| # | test_scenarios.py 테스트 ID | test_repl.py 키 | 유형 |
|---|---------------------------|----------------|------|
| 1 | P1-STANDARD | `p1std` | 전체 플로우 |
| 2 | P1-LOWFAT | `p1lf` | 전체 플로우 |
| - | *(없음)* | `p1lf_nogain` | REPL 전용 |
| - | *(없음)* | `p1lf_athlete` | REPL 전용 (§1.5 운동선수) |
| 3 | P1-SKIP-PASTOPSSITE | *(없음)* | 단위 검증 |
| 4 | P1-SKIP-WEIGHTGAIN | *(없음)* | 단위 검증 |
| 5 | P2-LIPO-ONLY | `p2a` | 전체 플로우 |
| 5 | P2-LIPO+TRANSFER | `p2b_stem` | 전체 플로우 |
| - | *(없음)* | `p2b_general` | REPL 전용 |
| 6 | P2-STEMCELL | *(없음)* | 단위 검증 |
| 7 | P3-FULL | `p3` | 전체 플로우 |
| - | *(없음)* | `p3_filler_exp` | REPL 전용 (§3.5 필러이력자) |
| 8 | P4-ABROAD | `p4abroad` | 전체 플로우 |
| 9 | P4-SEMIREMOTE | `p4semi` | 전체 플로우 |
| 10 | P4-STANDARD | `p4std` | REPL=전체, 단위 테스트=분기검증 |
| - | *(없음)* | `p4semi_s3` | REPL 전용 (§4.4 대전 S3) |
| 11 | P4-REGION-AUTOCALC | *(없음)* | 단위 검증 |
| 12 | P4-INBODY-SKIP | *(없음)* | 단위 검증 |
| 13 | P5-NO-CANCER-NO-IMPLANT | `p5_std` | 전체 플로우 |
| 15 | P5-WITH-IMPLANT | `p5_std_implant` | 전체 플로우 |
| 16 | P5-CONDITIONAL-WALK | `p5_conditional` | 전체 플로우 |
| 17 | P5-NOT-ALLOWED-WALK | `p5_not_allowed` | 전체 플로우 |
| 18 | P5-IMPLANT-SKIP | *(없음)* | 단위 검증 |
| 19 | P5-CANCER-NOT-SKIPPED | *(없음)* | 단위 검증 |
| 20 | P5-BRANCH-CANCER-NONE | *(없음)* | 단위 검증 |
| 21 | P5-BRANCH-CANCER-CONDITIONAL | *(없음)* | 단위 검증 |
| 22 | P5-BRANCH-CANCER-NOT-ALLOWED | *(없음)* | 단위 검증 |
| 23 | PROTOCOL-MODE-SKIP | *(없음)* | 단위 검증 |

> **참고**: P5 분기점은 `p5AskMedical`이며, `p5AskDetail`에서 6개 CHECKS(breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite)를 수집한 후, `p5AskMedical`에서 보형물 상세 2개(implantCondition, implantOriginHospital)만 conditional 수집합니다.

---

## test_scenarios.py 테스트 목록 (23개)

| # | 테스트 ID | 페르소나 | 유형 | 검증 내용 |
|---|----------|---------|------|----------|
| 1 | P1-STANDARD | slimBody | 전체 플로우 | BMI≥23 → STANDARD 경로 |
| 2 | P1-LOWFAT | slimBody | 전체 플로우 | BMI<23 → LOW-FAT 경로 |
| 3 | P1-SKIP-PASTOPSSITE | slimBody | 단위 검증 | pastOps="없음" → pastOpsSite 스킵 |
| 4 | P1-SKIP-WEIGHTGAIN | slimBody | 단위 검증 | weightGainIntent=false → 스킵 |
| 5 | P2-LIPO-ONLY | lipoCustomer | 전체 플로우 | upsellAccept=false → InfoA |
| 6 | P2-LIPO+TRANSFER | lipoCustomer | 전체 플로우 | upsellAccept=true → InfoB (일반이식) |
| 7 | P2-STEMCELL | lipoCustomer | 단위 검증 | transferType=줄기세포 → Finalize 전이 |
| 8 | P3-FULL | skinTreatment | 전체 플로우 | 단일 선형 경로 |
| 9 | P4-ABROAD | longDistance | 전체 플로우 | ABROAD → FULL 프로토콜 |
| 10 | P4-SEMIREMOTE | longDistance | 전체 플로우 | 부산(S4) → SEMI-REMOTE |
| 11 | P4-STANDARD | longDistance | 단위 검증 | 서울(S1) → STANDARD 분기 |
| 12 | P4-REGION-AUTOCALC | longDistance | 단위 검증 | regionBucket 자동 매핑 (ABROAD/경기=S2) |
| 13 | P4-INBODY-SKIP | longDistance | 단위 검증 | inbodyAvailable=false → 업로드 스킵 |
| 14 | P5-NO-CANCER-NO-IMPLANT | revisionFatigue | 전체 플로우 | 암없음+보형물없음 → STANDARD |
| 15 | P5-WITH-IMPLANT | revisionFatigue | 전체 플로우 | 보형물있음 → 추가질문 필수 |
| 16 | P5-CONDITIONAL-WALK | revisionFatigue | 전체 플로우 | 암이력+부분절제 → CONDITIONAL 전체 경로 |
| 17 | P5-NOT-ALLOWED-WALK | revisionFatigue | 전체 플로우 | 암이력+완전절제 → NOT_ALLOWED 전체 경로 |
| 18 | P5-IMPLANT-SKIP | revisionFatigue | 단위 검증 | implantPresence=false → 스킵 확인 |
| 19 | P5-CANCER-NOT-SKIPPED | revisionFatigue | 단위 검증 | cancerSurgeryType 스킵 안됨 확인 |
| 20 | P5-BRANCH-CANCER-NONE | revisionFatigue | 단위 검증 | 암이력없음 → STANDARD 분기 |
| 21 | P5-BRANCH-CANCER-CONDITIONAL | revisionFatigue | 단위 검증 | 암이력+부분절제 → CONDITIONAL 분기 |
| 22 | P5-BRANCH-CANCER-NOT-ALLOWED | revisionFatigue | 단위 검증 | 암이력+완전절제 → NOT_ALLOWED 분기 |
| 23 | PROTOCOL-MODE-SKIP | 공통 | 단위 검증 | protocolMode는 항상 시스템 관리 |

---

## test_repl.py REPL 시나리오 (17개)

### 시나리오 키 목록

| 키 | 이름 | 페르소나 | 분기 조건 | 엑셀 근거 |
|----|------|---------|----------|----------|
| `p1std` | P1 STANDARD | slimBody | BMI≥23, weightGainIntent=false | §1.1~1.3 |
| `p1lf` | P1 LOW-FAT (증량 희망) | slimBody | BMI<23, weightGainIntent=true | §1.1~1.3 |
| `p1lf_nogain` | P1 LOW-FAT (증량 거부) | slimBody | BMI<23, weightGainIntent=false | §1.1~1.3 |
| `p1lf_athlete` | P1 LOW-FAT (운동선수) | slimBody | BMI<23, 운동선수 배경, 증량 희망 | **§1.5** |
| `p2a` | P2 흡입 단독 | lipoCustomer | upsellAccept=false | §2.1~2.3 |
| `p2b_stem` | P2 흡입+이식 (줄기세포) | lipoCustomer | upsellAccept=true, transferType=줄기세포 | §2.1~2.3 |
| `p2b_general` | P2 흡입+이식 (일반) | lipoCustomer | upsellAccept=true, transferType=일반 | §2.1~2.3 |
| `p3` | P3 피부시술 | skinTreatment | 분기 없음 (선형) | §3.1~3.3 |
| `p3_filler_exp` | P3 필러/보톡스 이력자 | skinTreatment | 분기 없음, 필러 잔여량 있음 | **§3.5** |
| `p4abroad` | P4 해외 (FULL) | longDistance | ABROAD | §4.1~4.3 |
| `p4semi` | P4 부산 (SEMI-REMOTE) | longDistance | 부산=S4 | §4.1~4.3 |
| `p4std` | P4 서울 (STANDARD) | longDistance | 서울=S1 | §4.1~4.3 |
| `p4semi_s3` | P4 대전 (SEMI-REMOTE S3) | longDistance | 대전=S3 | **§4.4** |
| `p5_std` | P5 STANDARD (암-/보형물-) | revisionFatigue | cancer=false, implant=false | §5.1~5.3 |
| `p5_std_implant` | P5 STANDARD (암-/보형물+) | revisionFatigue | cancer=false, implant=true | §5.1~5.3 |
| `p5_conditional` | P5 CONDITIONAL (암 부분절제) | revisionFatigue | cancer=true, 부분절제 | §5.1~5.3 |
| `p5_not_allowed` | P5 NOT_ALLOWED (암 전절제) | revisionFatigue | cancer=true, 전절제 | §5.1~5.3 |

> **신규 시나리오 3개**: `p1lf_athlete`(§1.5), `p3_filler_exp`(§3.5), `p4semi_s3`(§4.4)는 엑셀 판단기준 문서의 식별 질문·배경 기반으로 추가.

---

## 전체 플로우 상세

---

### #1. P1-STANDARD — 슬림바디 STANDARD (BMI≥23)

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI ≥ 23 → ruleBodyFatHigh → protocolMode = STANDARD
> **자동 계산**: BMI = 26.1 (165cm, 71kg)
> **조건 스킵**: weightGainPlan, nutritionConsult (weightGainIntent=false); pastOpsSite (pastOps="없음")

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p1CollectInfo | "키 165cm이고 몸무게 71kg이에요. 체지방률은 30%정도 되고, 보통이에요. 인바디는 있어요. 가슴 줄기세포 지방이식에 관심 있어요." | `bodyInfo`=165cm 71kg, `bodyFat`=30, `bodyType`=보통, `inbodyAvailable`=true | BMI 26.1 자동계산 |
| 2 | p1AskLifestyle | "주 3회 운동하고 있어요. 운동 강도는 중간이고 식단은 불규칙해요. 체중 증량은 필요 없어요." | `activityPattern`=주3회 운동, `exerciseLevel`=중간, `dietPattern`=불규칙, `weightGainIntent`=false | |
| 3 | p1AskDetail | "복부랑 허벅지에서 지방 채취 가능하고요, 과거 시술 이력은 없습니다." | `fatSourceAvailability`=복부, 허벅지, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 (pastOps="없음") |
| - | p1InformSurgery | *(자동 전이)* | `protocolMode`=STANDARD | ruleBodyFatHigh 분기 |
| 4 | p1InformInfo | "회복 가이드라인은 2주 압박복 착용으로 할게요." | `recoveryGuideline`=2주 압박복 착용 | weightGainPlan, nutritionConsult 스킵됨 |
| 5 | p1Confirm | "김지현입니다. 010-9876-5432에요. 다음달에 수술 가능하고, 재확인은 2주 후에 할게요." | `customerName`=김지현, `phoneNumber`=010-9876-5432, `surgeryWindow`=다음달, `recheckSchedule`=2주 후 | 종료 |

---

### #2. P1-LOWFAT — 슬림바디 LOW-FAT (BMI<23)

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI < 23 → ruleBodyFatLow → protocolMode = LOW-FAT
> **자동 계산**: BMI = 20.2 (165cm, 55kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p1CollectInfo | "165cm에 55kg이에요. 체지방 18%이고 마른체형입니다. 인바디는 없어요." | `bodyInfo`=165cm 55kg, `bodyFat`=18, `bodyType`=마른체형, `inbodyAvailable`=false | BMI 20.2 자동계산 |
| 2 | p1AskLifestyle | "운동은 거의 안 해요. 소식하는 편이고 체중 좀 늘리고 싶어요." | `activityPattern`=거의 안함, `exerciseLevel`=낮음, `dietPattern`=소식, `weightGainIntent`=true | weightGainIntent=true → 스킵 안됨 |
| 3 | p1AskDetail | "허벅지에 지방이 소량 있고, 시술 경험은 없습니다." | `fatSourceAvailability`=허벅지 소량, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 (pastOps="없음") |
| - | p1InformSurgery | *(자동 전이)* | `protocolMode`=LOW-FAT | ruleBodyFatLow 분기 |
| 4 | p1InformInfo | "한달에 3kg 증량 목표로 하고, 영양사 상담도 받고 싶어요. 회복은 3주 압박복이요." | `weightGainPlan`=한달 3kg 증량 목표, `nutritionConsult`=영양사 상담 희망, `recoveryGuideline`=3주 압박복 | 3개 모두 수집 필요 |
| 5 | p1Confirm | "이수진이에요. 010-1111-2222입니다. 2개월 후에 수술하고 1개월 후에 재방문할게요." | `customerName`=이수진, `phoneNumber`=010-1111-2222, `surgeryWindow`=2개월 후, `recheckSchedule`=1개월 후 | 종료 |

---

### #3. P1-LOWFAT-NOGAIN — 슬림바디 LOW-FAT (BMI<23, 증량 거부) `p1lf_nogain`

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI < 23 → LOW-FAT, weightGainIntent=false → skip(weightGainPlan, nutritionConsult)
> **자동 계산**: BMI = 19.7 (158cm, 49kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p1CollectInfo | "158cm 49kg이에요. 체지방 17%이고 마른편이에요. 인바디 있어요." | `bodyInfo`=158cm 49kg, `bodyFat`=17, `bodyType`=마른편, `inbodyAvailable`=true | BMI 19.7 자동계산 |
| 2 | p1AskLifestyle | "필라테스 주2회 해요. 식단은 규칙적이고 체중 증량은 안 할 거예요." | `activityPattern`=필라테스 주2회, `exerciseLevel`=낮음, `dietPattern`=규칙적, `weightGainIntent`=false | |
| 3 | p1AskDetail | "허벅지 안쪽에 지방 소량이요. 시술은 처음입니다." | `fatSourceAvailability`=허벅지 안쪽 소량, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 (pastOps="없음") |
| - | p1InformSurgery | *(자동 전이)* | `protocolMode`=LOW-FAT | ruleBodyFatLow 분기 |
| 4 | p1InformInfo | "회복은 2주 압박복으로 하겠습니다." | `recoveryGuideline`=2주 압박복 | weightGainPlan, nutritionConsult 스킵됨 |
| 5 | p1Confirm | "박서연이에요. 연락처는 010-3333-4444예요. 3주 후에 수술하고 2주 후 재확인할게요." | `customerName`=박서연, `phoneNumber`=010-3333-4444, `surgeryWindow`=3주 후, `recheckSchedule`=2주 후 | 종료 |

---

### #4. P1-LOWFAT-ATHLETE — 슬림바디 LOW-FAT (운동선수 배경) `p1lf_athlete` ★신규

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI = 19.5 → LOW-FAT, weightGainIntent=true → collect(weightGainPlan, nutritionConsult)
> **엑셀 근거**: §1.5 운동선수/피트니스 배경 식별 질문
> **자동 계산**: BMI = 19.5 (168cm, 55kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p1CollectInfo | "168cm 55kg이에요. 체지방률은 12%이고 마른 근육질이에요. 인바디 데이터 있어요." | `bodyInfo`=168cm 55kg, `bodyFat`=12, `bodyType`=마른 근육질, `inbodyAvailable`=true | BMI 19.5 자동계산 |
| 2 | p1AskLifestyle | "매일 웨이트 트레이닝해요. 운동 강도 매우 높고 고단백 식단 유지 중이에요. 대회 끝나면 체중 증량 할 수 있어요." | `activityPattern`=매일 웨이트 트레이닝, `exerciseLevel`=매우 높음, `dietPattern`=고단백 식단, `weightGainIntent`=true | 운동선수 배경 |
| 3 | p1AskDetail | "옆구리에 약간 지방이 있고요, 복부는 거의 없어요. 시술 경험 없습니다." | `fatSourceAvailability`=옆구리 소량, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 |
| - | p1InformSurgery | *(자동 전이)* | `protocolMode`=LOW-FAT | ruleBodyFatLow 분기 |
| 4 | p1InformInfo | "대회 후 2개월간 5kg 증량 목표로 하고 스포츠 영양사 상담도 받고 싶어요. 회복은 4주 압박복이요." | `weightGainPlan`=2개월 5kg 증량 목표, `nutritionConsult`=스포츠 영양사 상담 희망, `recoveryGuideline`=4주 압박복 | 3개 모두 수집 |
| 5 | p1Confirm | "최서윤이에요. 010-4321-8765에요. 대회 끝나고 3개월 후에 가슴 수술하고, 한달 뒤에 재확인할게요." | `customerName`=최서윤, `phoneNumber`=010-4321-8765, `surgeryWindow`=3개월 후, `recheckSchedule`=한달 뒤 | 종료 |

---

### #5. P2-LIPO-ONLY — 지방흡입 단독

> **경로**: p2PreCollect → p2Collect → p2AskLifestyle → p2AskDetail → p2InformSurgery → p2InformInfoA → p2Finalize
> **분기**: upsellAccept=false → lipoOnly → p2InformInfoA
> **자동 계산**: BMI = 23.3 (163cm, 62kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p2PreCollect | "163cm 62kg이고 다음주 화요일에 상담 가능해요. 가슴 볼륨이 고민이고 병력은 없습니다. 서지영 010-1234-5678입니다." | `bodyInfo`=163cm 62kg, `schedule`=다음주 화요일, `concernArea`=가슴 볼륨, `medicalHistory`=없음, `basicInfo`=서지영 010-1234-5678 | BMI 23.3 자동계산 |
| 2 | p2Collect | "교통편 제약은 없어요." | `travelConstraint`=없음 | bodyInfo/schedule 이전 스텝에서 수집됨 |
| 3 | p2AskLifestyle | "주3회 필라테스하고 운동 강도 중간이에요. 비흡연이고 회복 기간 2주 가능해요. 사무직입니다." | `activityPattern`=주3회 필라테스, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주, `jobIntensity`=사무직 | |
| 4 | p2AskDetail | "복부에 지방 충분하고 복부 옆구리 흡입 원해요. 가슴 볼륨 업이 목표고 위험요소 없어요. 과거 시술 없습니다." | `fatSourceAvailability`=복부 충분, `lipoArea`=복부, 옆구리, `lipoGoal`=가슴 볼륨 업, `riskFactor`=없음, `pastOps`=없음 | |
| 5 | p2InformSurgery | "일단 흡입 단독으로 하고 싶어요. 가슴 이식은 나중에 고려할게요. 멍이 좀 걱정되고 비용은 중간 정도면 좋겠어요." | `planPreference`=흡입 단독, `upsellAccept`=false, `concernSideEffect`=멍, `costSensitivity`=중간, `recoveryAllowance`=2주 | **lipoOnly** 분기 → InfoA |
| 6 | p2InformInfoA | "회복은 2주 압박복, 복부 전체 흡입으로 진행하고 비용은 300-500만원 사이면 좋겠어요." | `recoveryTimeline`=2주 압박복, `lipoPlanDetail`=복부 전체 흡입, `costRange`=300-500만원 | |
| 7 | p2Finalize | "사전검사 필요하고 다음주 목요일에 방문할게요. 당일 수술은 안 되고 예약 의사 있습니다." | `precheckRequired`=true, `visitSchedule`=다음주 목요일, `sameDayPossible`=false, `reservationIntent`=true | 종료 |

---

### #6. P2-LIPO+TRANSFER (줄기세포) — 흡입+이식 `p2b_stem`

> **경로**: p2PreCollect → p2Collect → p2AskLifestyle → p2AskDetail → p2InformSurgery → p2InformInfoB → p2Finalize
> **분기**: upsellAccept=true → lipoGraft → p2InformInfoB, transferType=줄기세포
> **자동 계산**: BMI = 23.0 (168cm, 65kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p2PreCollect | "168cm 65kg입니다. 이번주 금요일 가능하고 가슴 볼륨이 고민이에요. 병력 없고 이영희 010-5678-1234예요." | `bodyInfo`=168cm 65kg, `schedule`=이번주 금요일, `concernArea`=가슴 볼륨, `medicalHistory`=없음, `basicInfo`=이영희 010-5678-1234 | BMI 23.0 자동계산 |
| 2 | p2Collect | "이동 제약 없습니다." | `travelConstraint`=없음 | |
| 3 | p2AskLifestyle | "주 2회 운동하고 중간 강도예요. 담배 안 피우고 3주 회복 가능합니다. 프리랜서에요." | `activityPattern`=주2회, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=3주, `jobIntensity`=프리랜서 | |
| 4 | p2AskDetail | "허벅지에서 지방 채취하고 허벅지 안쪽 흡입 원해요. 이식용 지방 확보가 목적이고 위험요소 없어요. 과거 시술 없음." | `fatSourceAvailability`=허벅지, `lipoArea`=허벅지 안쪽, `lipoGoal`=이식용 지방 확보, `riskFactor`=없음, `pastOps`=없음 | |
| 5 | p2InformSurgery | "흡입이랑 이식 같이 하고 싶어요. 부기가 걱정되고 비용은 좀 높아도 괜찮아요." | `planPreference`=흡입+이식, `upsellAccept`=true, `concernSideEffect`=부기, `costSensitivity`=낮음, `recoveryAllowance`=3주 | **lipoGraft** 분기 → InfoB |
| 6 | p2InformInfoB | "줄기세포 이식으로 하고 싶어요. 줄기세포 이식 가슴 볼륨 보충 계획이에요. 회복 4주 예상하고 자연스러운 볼륨 원해요. 800-1200만원 예산이에요." | `transferType`=줄기세포, `transferPlanDetail`=줄기세포 이식 가슴 볼륨 보충, `recoveryTimeline`=4주 회복, `graftExpectation`=자연스러운 볼륨, `costRange`=800-1200만원 | **transferPlanDetail** 추가 수집 |
| 7 | p2Finalize | "사전검사 하고 다음주 월요일에 방문합니다. 당일 수술도 가능하면 좋겠고 예약할게요." | `precheckRequired`=true, `visitSchedule`=다음주 월요일, `sameDayPossible`=true, `reservationIntent`=true | 종료 |

---

### #7. P2-LIPO+TRANSFER (일반) — 흡입+이식 일반 `p2b_general`

> **경로**: p2PreCollect → p2Collect → p2AskLifestyle → p2AskDetail → p2InformSurgery → p2InformInfoB → p2Finalize
> **분기**: upsellAccept=true → lipoGraft → p2InformInfoB, transferType=일반
> **자동 계산**: BMI = 23.5 (175cm, 72kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p2PreCollect | "175cm 72kg이에요. 이번주 토요일 가능하고 가슴볼륨이 고민입니다. 병력 없고 한소희 010-2222-3333이에요." | `bodyInfo`=175cm 72kg, `schedule`=이번주 토요일, `concernArea`=가슴볼륨, `medicalHistory`=없음, `basicInfo`=한소희 010-2222-3333 | |
| 2 | p2Collect | "교통편 문제없어요." | `travelConstraint`=없음 | |
| 3 | p2AskLifestyle | "주4회 수영하고 강도 중간이에요. 비흡연이고 2주 회복 가능합니다. 교사에요." | `activityPattern`=주4회 수영, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주, `jobIntensity`=교사 | |
| 4 | p2AskDetail | "복부에 지방 넉넉하고 가슴 볼륨업이 목표예요. 특별한 위험요소 없어요. 시술 이력 없음." | `fatSourceAvailability`=복부 넉넉, `lipoArea`=가슴, `lipoGoal`=가슴 볼륨업, `riskFactor`=없음, `pastOps`=없음 | |
| 5 | p2InformSurgery | "이식도 함께 하고 싶어요. 비용은 적당하면 좋겠고 붓기가 걱정이에요." | `planPreference`=흡입+이식, `upsellAccept`=true, `concernSideEffect`=붓기, `costSensitivity`=중간, `recoveryAllowance`=2주 | **lipoGraft** 분기 → InfoB |
| 6 | p2InformInfoB | "일반 이식으로 할게요. 일반 이식 가슴 볼륨 보충할 계획이에요. 회복 2주 예상하고 자연스러운 결과 원해요. 500-700만원 예산입니다." | `transferType`=일반, `transferPlanDetail`=일반 이식 가슴 볼륨 보충, `recoveryTimeline`=2주 회복, `graftExpectation`=자연스러운 결과, `costRange`=500-700만원 | **transferPlanDetail** 추가 수집 |
| 7 | p2Finalize | "사전검사 하고 다음주 수요일 방문합니다. 당일 수술은 안 되고 예약할게요." | `precheckRequired`=true, `visitSchedule`=다음주 수요일, `sameDayPossible`=false, `reservationIntent`=true | 종료 |

---

### #8. P3-FULL — 피부시술 가슴성형 전후 피부관리

> **경로**: p3Collect → p3AskLifestyle → p3AskDetail → p3AskSurgery → p3InformSugery → p3Confirm
> **분기**: 없음 (단일 선형 경로)
> **자동 계산**: BMI = 19.1 (162cm, 50kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p3Collect | "162cm 50kg이고 체지방 22%예요. 건성 피부에 가슴 부위 탄력 저하가 고민이에요." | `bodyInfo`=162cm 50kg, `bodyFat`=22, `skinType`=건성, `skinCondition`=가슴 부위 탄력 저하 | BMI 19.1 자동계산 |
| 2 | p3AskLifestyle | "요가 주2회 하고요. 야외 근무라 자외선 노출이 많아요. 기초 화장품만 쓰고 담배는 안 펴요." | `activityPattern`=요가 주2회, `sunExposure`=높음 (야외 근무), `skincareRoutine`=기초 화장품만 사용, `smoking`=false | |
| 3 | p3AskDetail | "허벅지 지방 있고 필러 잔여물 없어요. 알레르기 없고 보톡스 3회 맞았어요. 이마 눈가에 맞았고 6개월 주기로 했습니다." | `fatSourceAvailability`=허벅지, `fillerRemaining`=false, `allergyHistory`=없음, `pastOps`=보톡스 3회, `pastOpsSite`=이마, 눈가, `botoxCycle`=6개월 주기 | pastOps≠"없음" → pastOpsSite 수집 |
| 4 | p3AskSurgery | "가슴 부위 수술 전후 피부가 고민이에요. 수술 후 피부 탄력 회복 원하고 1년 이상 지속되면 좋겠어요." | `concernArea`=가슴 부위 수술 전후 피부, `desiredEffect`=수술 후 피부 탄력 회복, `durabilityExpectation`=1년 이상 | |
| - | p3InformSugery | *(자동 전이)* | - | CheckItem 없음 |
| 5 | p3Confirm | "최윤아예요. 010-4444-5555입니다. 이번달 내에 하고 싶고 다음주 수요일 방문 가능해요. 가슴성형 전후 피부관리로 계획이에요." | `customerName`=최윤아, `phoneNumber`=010-4444-5555, `surgeryWindow`=이번달 내, `visitSchedule`=다음주 수요일, `procedurePlan`=가슴성형 전후 피부관리 | 종료 |

---

### #9. P3-FILLER-EXP — 피부시술 필러/보톡스 이력자 `p3_filler_exp` ★신규

> **경로**: p3Collect → p3AskLifestyle → p3AskDetail → p3AskSurgery → p3InformSugery → p3Confirm
> **분기**: 없음 (단일 선형 경로)
> **엑셀 근거**: §3.5 과거 시술 경험 식별 질문
> **자동 계산**: BMI = 19.4 (167cm, 54kg)
> **특이점**: `fillerRemaining`=약간 남아있음 (기존 p3에서는 false)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p3Collect | "167cm 54kg이고 체지방 20%예요. 복합성 피부에 팔자주름이랑 볼 꺼짐이 고민이에요." | `bodyInfo`=167cm 54kg, `bodyFat`=20, `skinType`=복합성, `skinCondition`=팔자주름, 볼 꺼짐 | BMI 19.4 자동계산 |
| 2 | p3AskLifestyle | "필라테스 주 3회 해요. 실내 근무라 자외선 노출 적은 편이고 스킨케어 루틴이 있어요. 비흡연이에요." | `activityPattern`=필라테스 주3회, `sunExposure`=낮음, `skincareRoutine`=스킨케어 루틴 있음, `smoking`=false | |
| 3 | p3AskDetail | "허벅지에 지방 있고 필러 잔여물이 아직 좀 남아있어요. 알레르기 없고 필러 5회, 보톡스 4회 맞았어요. 팔자주름이랑 이마에 맞았고 4개월 주기로 했었어요." | `fatSourceAvailability`=허벅지, `fillerRemaining`=약간 남아있음, `allergyHistory`=없음, `pastOps`=필러 5회, 보톡스 4회, `pastOpsSite`=팔자주름, 이마, `botoxCycle`=4개월 주기 | 필러 잔여량 **있음** |
| 4 | p3AskSurgery | "팔자주름 개선이 제일 급하고 볼 볼륨도 채우고 싶어요. 동안 느낌으로 자연스러운 효과 원하고 최소 2년은 유지되면 좋겠어요." | `concernArea`=팔자주름, 볼 볼륨, `desiredEffect`=동안 느낌 자연스러운 효과, `durabilityExpectation`=최소 2년 | |
| - | p3InformSugery | *(자동 전이)* | - | CheckItem 없음 |
| 5 | p3Confirm | "김예진이에요. 010-7654-3210이요. 다음달 초에 하고 싶고 이번주 금요일 방문 가능해요. 줄기세포 지방이식이랑 리프팅 결합으로요." | `customerName`=김예진, `phoneNumber`=010-7654-3210, `surgeryWindow`=다음달 초, `visitSchedule`=이번주 금요일, `procedurePlan`=줄기세포 지방이식 + 리프팅 | 종료 |

---

### #10. P4-ABROAD — 원거리 해외 (FULL)

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: ABROAD → regionBucket=ABROAD → protocolMode = FULL
> **자동 계산**: regionBucket=ABROAD, BMI=23.0 (172cm, 68kg)
> **조건 스킵**: domesticDistrict (ABROAD), inbodyPhotoUpload (inbodyAvailable=false), pastOpsSite (pastOps="없음")

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p4PreCollect | "해외에 살고 있어요. 2주 정도 한국 방문 가능하고 비자가 필요해요." | `residenceCountry`=ABROAD, `visitPeriod`=2주, `travelConstraint`=비자 필요 | regionBucket=ABROAD 자동, domesticDistrict 스킵 |
| 2 | p4Collect | "172cm 68kg이고 체지방 20%예요. 인바디 데이터는 없어요." | `bodyInfo`=172cm 68kg, `bodyFat`=20, `inbodyAvailable`=false | BMI 23.0 자동, inbodyPhotoUpload 스킵 |
| 3 | p4AskLifestyle | "주 3회 조깅하고 중간 강도예요. 담배 안 피고 3주 회복 가능합니다." | `activityPattern`=주3회 조깅, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=3주 | |
| 4 | p4AskDetail | "복부에서 지방 채취 가능하고 과거 시술 없어요." | `fatSourceAvailability`=복부, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 |
| - | p4InformSurgery | *(자동 전이)* | - | CheckItem 없음 |
| 5 | p4InformInfo | "사전검사 2시간 예상하고 체형 사진이랑 서류 업로드했어요." | `precheckTimeEstimate`=2시간, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | |
| 6 | p4Confirm | "다음달에 수술하고 보증금 예약할게요." | `surgeryWindow`=다음달, `depositReservation`=true | |
| 7 | p4Finalize | "정하나에요. 010-6666-7777입니다. 현지 병원 연계로 사후관리하고 수술 후 2주 원격 상담 받을게요." | `customerName`=정하나, `phoneNumber`=010-6666-7777, `aftercarePlan`=현지 병원 연계, `followupSchedule`=수술 후 2주 원격 상담 | 종료 |

---

### #11. P4-SEMIREMOTE — 원거리 부산 (SEMI-REMOTE)

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: 부산 → regionBucket=S4 → protocolMode = SEMI-REMOTE
> **자동 계산**: regionBucket=S4, BMI=21.3 (162cm, 56kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p4PreCollect | "한국 부산에 살고 있어요. 3일 정도 서울 방문 가능하고 KTX 이용합니다." | `residenceCountry`=한국, `domesticDistrict`=부산, `visitPeriod`=3일, `travelConstraint`=KTX 이용 | regionBucket=S4 자동, SEMI-REMOTE 분기 |
| 2 | p4Collect | "162cm 56kg이고 체지방 25%예요. 인바디 있고 사진도 업로드했어요." | `bodyInfo`=162cm 56kg, `bodyFat`=25, `inbodyAvailable`=true, `inbodyPhotoUpload`=uploaded | BMI 21.3 자동계산 |
| 3 | p4AskLifestyle | "주3회 필라테스 다니고 중간 강도예요. 비흡연이고 2주 회복 가능합니다." | `activityPattern`=주3회 필라테스, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주 | |
| 4 | p4AskDetail | "복부 허벅지에서 채취 가능. 시술 이력 없습니다." | `fatSourceAvailability`=복부, 허벅지, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 |
| - | p4InformSurgery | *(자동 전이)* | - | CheckItem 없음 |
| 5 | p4InformInfo | "사전검사 1시간이면 되고 사진 서류 다 올렸어요." | `precheckTimeEstimate`=1시간, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | |
| 6 | p4Confirm | "이번달에 수술하고 보증금 입금합니다." | `surgeryWindow`=이번달, `depositReservation`=true | |
| 7 | p4Finalize | "윤다혜예요. 010-8888-9999입니다. 지역 병원 연계 사후관리하고 1주 후 재방문할게요." | `customerName`=윤다혜, `phoneNumber`=010-8888-9999, `aftercarePlan`=지역 병원 연계, `followupSchedule`=1주 후 재방문 | 종료 |

---

### #12. P4-STANDARD — 원거리 서울 (STANDARD) `p4std`

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: 서울 → regionBucket=S1 → protocolMode = STANDARD
> **자동 계산**: regionBucket=S1, BMI=21.8 (170cm, 63kg)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p4PreCollect | "서울에 살고 있어요. 수시로 방문 가능하고 교통 제약 없습니다." | `residenceCountry`=한국, `domesticDistrict`=서울, `visitPeriod`=수시 가능, `travelConstraint`=없음 | regionBucket=S1 자동 |
| 2 | p4Collect | "170cm 63kg이고 체지방 23%예요. 인바디 있고 사진 업로드했어요." | `bodyInfo`=170cm 63kg, `bodyFat`=23, `inbodyAvailable`=true, `inbodyPhotoUpload`=uploaded | BMI 21.8 자동계산 |
| 3 | p4AskLifestyle | "주3회 러닝하고 중간 강도예요. 비흡연이고 2주 회복 가능합니다." | `activityPattern`=주3회 러닝, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주 | |
| 4 | p4AskDetail | "복부 지방 충분하고 시술 이력 없어요." | `fatSourceAvailability`=복부 충분, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 |
| - | p4InformSurgery | *(자동 전이)* | - | CheckItem 없음 |
| 5 | p4InformInfo | "사전검사 30분이면 되고 사진 서류 준비됐어요." | `precheckTimeEstimate`=30분, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | |
| 6 | p4Confirm | "이번주에 수술하고 보증금 납부하겠습니다." | `surgeryWindow`=이번주, `depositReservation`=true | |
| 7 | p4Finalize | "윤서아예요. 010-5555-6666입니다. 직접 내원 사후관리하고 1주 후 내원할게요." | `customerName`=윤서아, `phoneNumber`=010-5555-6666, `aftercarePlan`=직접 내원, `followupSchedule`=1주 후 내원 | 종료 |

---

### #13. P4-SEMIREMOTE-S3 — 원거리 대전 (SEMI-REMOTE S3) `p4semi_s3` ★신규

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: 대전 → regionBucket=S3 → protocolMode = SEMI-REMOTE
> **엑셀 근거**: §4.4 Step 1 권역 식별
> **자동 계산**: regionBucket=S3, BMI=20.3 (160cm, 52kg)
> **조건 스킵**: inbodyPhotoUpload (inbodyAvailable=false), pastOpsSite (pastOps="없음")

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p4PreCollect | "한국 대전에 살고 있어요. 주말 이용해서 2일 정도 서울 방문 가능하고 KTX로 이동합니다." | `residenceCountry`=한국, `domesticDistrict`=대전, `visitPeriod`=2일, `travelConstraint`=KTX 이용 | regionBucket=S3 자동, SEMI-REMOTE |
| 2 | p4Collect | "160cm 52kg이고 체지방 22%예요. 인바디 없어요." | `bodyInfo`=160cm 52kg, `bodyFat`=22, `inbodyAvailable`=false | BMI 20.3 자동, inbodyPhotoUpload 스킵 |
| 3 | p4AskLifestyle | "주2회 수영하고 중간 강도예요. 비흡연이고 1주 회복 가능합니다." | `activityPattern`=주2회 수영, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=1주 | |
| 4 | p4AskDetail | "허벅지에서 지방 채취 가능하고 시술 이력 없습니다." | `fatSourceAvailability`=허벅지, `pastOps`=없음, `pastOpsSite`=없음 | pastOpsSite 스킵 |
| - | p4InformSurgery | *(자동 전이)* | - | CheckItem 없음 |
| 5 | p4InformInfo | "사전검사 1시간이면 되고 사진이랑 서류 업로드했어요." | `precheckTimeEstimate`=1시간, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | |
| 6 | p4Confirm | "다음주에 수술하고 보증금 예약합니다." | `surgeryWindow`=다음주, `depositReservation`=true | |
| 7 | p4Finalize | "장예린이에요. 010-3456-7890입니다. 대전 로컬 병원 연계 사후관리하고 2주 후 사진 원격 상담 받을게요." | `customerName`=장예린, `phoneNumber`=010-3456-7890, `aftercarePlan`=대전 로컬 병원 연계, `followupSchedule`=2주 후 사진 원격 상담 | 종료 |

---

### #14. P5-NO-CANCER-NO-IMPLANT — 재수술 STANDARD `p5_std`

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → p5AskMedical → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=false → ruleCancerNone → protocolMode = STANDARD (분기점: p5AskMedical)
> **자동 계산**: BMI = 21.5 (160cm, 55kg)
> **조건 스킵**: implantCondition, implantOriginHospital (implantPresence=false)
> **핵심**: p5AskDetail에서 6개 CHECKS 수집, p5AskMedical은 보형물 상세만 (conditional)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p5Collect | "160cm 55kg이고 체지방 24%예요. 보통 체형이에요." | `bodyInfo`=160cm 55kg, `bodyFat`=24, `bodyType`=보통 | BMI 21.5 자동계산 |
| 2 | p5AskLifestyle | "가끔 산책하고 비흡연이에요. 사무직이고 2주 회복 가능해요." | `activityPattern`=가끔 산책, `smoking`=false, `workConstraint`=사무직, `recoveryAllowance`=2주 | |
| 3 | p5AskDetail | "유방암 이력 없어요. 보형물도 없습니다. 암 수술은 해당없어요. 복부 지방 있고 가슴 확대 1회 했었어요. 가슴 부위였어요." | `breastCancerHistory`=false, `implantPresence`=false, `cancerSurgeryType`=해당없음, `fatSourceAvailability`=복부, `pastOps`=가슴 확대 1회, `pastOpsSite`=가슴 | **6개 CHECKS** 한 턴에 수집 |
| 4 | p5AskMedical | "보형물 관련은 해당없습니다." | *(빈 slots)* | implant 스킵 → 수집할 항목 없음 |
| - | p5InformSurgery | *(자동 전이)* | `protocolMode`=STANDARD | ruleCancerNone 분기 |
| 5 | p5InformInfo | "정기 검진으로 사후관리하고 실리콘 시트로 흉터 관리할게요. 위험성 상세히 설명해주세요." | `aftercarePlan`=정기 검진, `scarManagement`=실리콘 시트, `riskExplanationLevel`=상세 | |
| 6 | p5Confirm | "강미래에요. 010-7777-8888입니다. 다음달 수술하고 다음주 금요일에 방문할게요. 자가조직 재건으로 계획합니다." | `customerName`=강미래, `phoneNumber`=010-7777-8888, `surgeryWindow`=다음달, `visitSchedule`=다음주 금요일, `procedurePlan`=자가조직 재건 | 종료 |

---

### #15. P5-WITH-IMPLANT — 재수술 STANDARD (보형물 있음) `p5_std_implant`

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → p5AskMedical → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=false → ruleCancerNone → STANDARD
> **자동 계산**: BMI = 21.8 (163cm, 58kg)
> **핵심**: implantPresence=true → implantCondition, implantOriginHospital **수집 필수** (p5AskMedical)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p5Collect | "163cm 58kg이고 체지방 26%예요. 보통 체형입니다." | `bodyInfo`=163cm 58kg, `bodyFat`=26, `bodyType`=보통 | BMI 21.8 자동계산 |
| 2 | p5AskLifestyle | "주2회 걷기 운동하고 비흡연이에요. 재택근무라 제약 없고 3주 회복 가능해요." | `activityPattern`=주2회 걷기, `smoking`=false, `workConstraint`=재택근무, `recoveryAllowance`=3주 | |
| 3 | p5AskDetail | "유방암 이력 없어요. 보형물 있습니다. 암 수술은 해당없어요. 복부 지방 있고 가슴 확대 2회 했었어요. 가슴 부위에요." | `breastCancerHistory`=false, `implantPresence`=true, `cancerSurgeryType`=해당없음, `fatSourceAvailability`=복부, `pastOps`=가슴 확대 2회, `pastOpsSite`=가슴 | **6개 CHECKS** |
| 4 | p5AskMedical | "보형물 상태는 구축이 왔어요. 이전에 A성형외과에서 했습니다." | `implantCondition`=구축, `implantOriginHospital`=A성형외과 | **2개 CHECKS** 필수 수집 |
| - | p5InformSurgery | *(자동 전이)* | `protocolMode`=STANDARD | ruleCancerNone 분기 |
| 5 | p5InformInfo | "월 1회 검진으로 사후관리하고 압박밴드로 흉터 관리할게요. 위험성 기본 설명이면 돼요." | `aftercarePlan`=월 1회 검진, `scarManagement`=압박밴드, `riskExplanationLevel`=기본 | |
| 6 | p5Confirm | "노은지에요. 010-1212-3434입니다. 2개월 후 수술하고 다음주 화요일 방문할게요. 보형물 교체로 진행합니다." | `customerName`=노은지, `phoneNumber`=010-1212-3434, `surgeryWindow`=2개월 후, `visitSchedule`=다음주 화요일, `procedurePlan`=보형물 교체 | 종료 |

---

### #16. P5-CONDITIONAL — 재수술 CONDITIONAL (암+부분절제) `p5_conditional`

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → p5AskMedical → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=true + cancerSurgeryType=부분 → CONDITIONAL
> **자동 계산**: BMI = 21.6 (155cm, 52kg)
> **조건 스킵**: implantCondition, implantOriginHospital (implantPresence=false)

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p5Collect | "155cm 52kg이고 체지방 22%예요. 마른편이에요." | `bodyInfo`=155cm 52kg, `bodyFat`=22, `bodyType`=마른편 | |
| 2 | p5AskLifestyle | "산책 위주로 운동하고 비흡연이에요. 사무직이고 4주 회복 가능합니다." | `activityPattern`=산책 위주, `smoking`=false, `workConstraint`=사무직, `recoveryAllowance`=4주 | |
| 3 | p5AskDetail | "유방암 이력이 있어요. 부분절제 수술 받았습니다. 보형물은 없어요. 허벅지 지방 있고 유방 재건 1회 했었어요. 가슴 부위입니다." | `breastCancerHistory`=true, `implantPresence`=false, `cancerSurgeryType`=부분, `fatSourceAvailability`=허벅지, `pastOps`=유방 재건 1회, `pastOpsSite`=가슴 | **6개 CHECKS** |
| 4 | p5AskMedical | "보형물 관련은 해당없어요." | *(빈 slots)* | implant 스킵 |
| - | p5InformSurgery | *(자동 전이)* | `protocolMode`=CONDITIONAL | ruleCancerConditional 분기 |
| 5 | p5InformInfo | "주치의 협진으로 사후관리하고 실리콘 시트 사용할게요. 위험성 상세히 알고 싶어요." | `aftercarePlan`=주치의 협진, `scarManagement`=실리콘 시트, `riskExplanationLevel`=상세 | |
| 6 | p5Confirm | "오수연이에요. 010-5656-7878입니다. 3개월 후 수술 예정이고 다음주 목요일에 방문할게요. 자가조직 재건으로요." | `customerName`=오수연, `phoneNumber`=010-5656-7878, `surgeryWindow`=3개월 후, `visitSchedule`=다음주 목요일, `procedurePlan`=자가조직 재건 | 종료 |

---

### #17. P5-NOT-ALLOWED — 재수술 NOT_ALLOWED (암+전절제) `p5_not_allowed`

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → p5AskMedical → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=true + cancerSurgeryType=완전 → NOT_ALLOWED
> **자동 계산**: BMI = 20.3 (157cm, 50kg)
> **핵심**: 시술 불가 판정, 보형물 있음 → implant 정보 필수

| Turn | Step | 입력 내용 | 추출 Slots | 비고 |
|------|------|----------|-----------|------|
| 1 | p5Collect | "157cm 50kg이고 체지방 20%예요. 마른편이에요." | `bodyInfo`=157cm 50kg, `bodyFat`=20, `bodyType`=마른편 | |
| 2 | p5AskLifestyle | "운동은 거의 안 하고 비흡연이에요. 주부이고 2주 회복 가능해요." | `activityPattern`=거의 안함, `smoking`=false, `workConstraint`=주부, `recoveryAllowance`=2주 | |
| 3 | p5AskDetail | "유방암 이력 있어요. 전절제 수술 받았습니다. 보형물도 있어요. 복부 지방 있고 가슴 수술 3회 했어요. 가슴 부위예요." | `breastCancerHistory`=true, `implantPresence`=true, `cancerSurgeryType`=완전, `fatSourceAvailability`=복부, `pastOps`=가슴 수술 3회, `pastOpsSite`=가슴 | **6개 CHECKS** |
| 4 | p5AskMedical | "보형물 상태는 파손이에요. B성형외과에서 했습니다." | `implantCondition`=파손, `implantOriginHospital`=B성형외과 | **2개 CHECKS** 필수 수집 |
| - | p5InformSurgery | *(자동 전이)* | `protocolMode`=NOT_ALLOWED | ruleCancerNotAllowed 분기 |
| 5 | p5InformInfo | "종합 사후관리 원하고 레이저 흉터 치료할게요. 위험성 상세 설명 부탁드려요." | `aftercarePlan`=종합 사후관리, `scarManagement`=레이저 흉터 치료, `riskExplanationLevel`=상세 | |
| 6 | p5Confirm | "임소정이에요. 010-9090-1010입니다. 상담 후 결정할게요. 다음주 월요일에 방문하고 대안 시술 상담으로요." | `customerName`=임소정, `phoneNumber`=010-9090-1010, `surgeryWindow`=상담 후 결정, `visitSchedule`=다음주 월요일, `procedurePlan`=대안 시술 상담 | 종료 |

---

## test_scenarios.py 단위 검증 시나리오 (11개)

아래 테스트들은 전체 플로우가 아닌, **특정 스텝/조건에서의 동작만 검증**합니다. (test_scenarios.py 전용, test_repl.py에는 없음)

---

### #3. P1-SKIP-WEIGHTGAIN — weightGainIntent=false 스킵 확인

> **검증 스텝**: p1InformInfo
> **검증 내용**: weightGainIntent=false일 때 weightGainPlan, nutritionConsult가 스킵되는지

| 조건 | 입력 Slots | 검증 |
|------|-----------|------|
| 스텝 p1InformInfo에서 | `weightGainIntent`=false, `recoveryGuideline`=2주 | `should_skip("weightGainPlan")` → **true** |
| | | `should_skip("nutritionConsult")` → **true** |
| | | `_are_step_checks_filled("p1InformInfo")` → **true** (recoveryGuideline만으로 통과) |

---

### #6. P2-STEMCELL — 줄기세포 이식 전이 확인

> **검증 스텝**: p2InformInfoB
> **검증 내용**: transferType=줄기세포일 때 p2Finalize로 정상 전이되는지

| 조건 | 입력 Slots | 검증 |
|------|-----------|------|
| 스텝 p2InformInfoB에서 | `upsellAccept`=true, `transferType`=줄기세포, `recoveryTimeline`=4주, `graftExpectation`=줄기세포 이식, `costRange`=800-1200만원, `transferPlanDetail`=줄기세포 이식 계획 | `next_step()` → **p2Finalize** |

---

### #10. P4-STANDARD — 서울 거주 STANDARD 분기

> **검증 스텝**: p4PreCollect
> **검증 내용**: 서울 거주(S1) → STANDARD 프로토콜 분기

| 조건 | 입력 Slots | 검증 |
|------|-----------|------|
| 스텝 p4PreCollect에서 | `residenceCountry`=한국, `domesticDistrict`=서울, `visitPeriod`=당일, `travelConstraint`=없음 | `regionBucket` → **S1** |
| | | `next_step().via` → **branching** (STANDARD) |

---

### #11. P4-REGION-AUTOCALC — regionBucket 자동 매핑

> **검증 스텝**: p4PreCollect
> **검증 내용**: regionBucket 자동 계산 + domesticDistrict 스킵 로직

| 케이스 | 입력 Slots | 검증 |
|--------|-----------|------|
| 해외 거주 | `residenceCountry`=ABROAD | `should_skip("domesticDistrict")` → **true** |
| | | `regionBucket` → **ABROAD** |
| 국내 (지역 미입력) | `residenceCountry`=한국 | `should_skip("domesticDistrict")` → **false** |
| 국내 경기 | `residenceCountry`=한국, `domesticDistrict`=경기 | `regionBucket` → **S2** |

---

### #12. P4-INBODY-SKIP — inbody 사진 스킵

> **검증 스텝**: p4Collect
> **검증 내용**: inbodyAvailable=false → inbodyPhotoUpload 스킵

| 케이스 | 입력 Slots | 검증 |
|--------|-----------|------|
| 인바디 없음 | `inbodyAvailable`=false | `should_skip("inbodyPhotoUpload")` → **true** |
| 인바디 있음 | `inbodyAvailable`=true | `should_skip("inbodyPhotoUpload")` → **false** |

---

### #15. P5-IMPLANT-SKIP — 보형물 스킵 로직

> **검증 스텝**: p5AskMedical
> **검증 내용**: implantPresence 값에 따른 스킵 동작 (implantCondition/Hospital은 p5AskMedical의 CheckItem)

| 케이스 | 입력 Slots | 검증 |
|--------|-----------|------|
| 보형물 없음 | `implantPresence`=false | `should_skip("implantCondition")` → **true** |
| | | `should_skip("implantOriginHospital")` → **true** |
| 보형물 있음 | `implantPresence`=true | `should_skip("implantCondition")` → **false** |
| | | `should_skip("implantOriginHospital")` → **false** |

---

### #16. P5-CANCER-NOT-SKIPPED — cancerSurgeryType 스킵 안됨

> **검증 스텝**: p5AskDetail
> **검증 내용**: breastCancerHistory=false여도 cancerSurgeryType은 항상 물어봄

| 조건 | 입력 Slots | 검증 |
|------|-----------|------|
| 유방암 없음 | `breastCancerHistory`=false | `should_skip("cancerSurgeryType")` → **false** |

> **참고**: 유방암 외 다른 암이 있을 수 있어서 항상 수집

---

### #17. P5-BRANCH-CANCER-NONE — 암이력 없음 → STANDARD

> **검증 스텝**: p5AskMedical (분기점)
> **검증 내용**: 암이력 없을 때 분기 결과

| 조건 | 입력 Slots | 검증 |
|------|-----------|------|
| 스텝 p5AskMedical에서 | `breastCancerHistory`=false, `implantPresence`=false, `cancerSurgeryType`=해당없음, `fatSourceAvailability`=복부, `pastOps`=1회, `pastOpsSite`=가슴 (이전 Step p5AskDetail에서 수집) | `next_step().via` → **branching** |
| | | `protocolMode` → **STANDARD** |

---

### #18. P5-BRANCH-CANCER-CONDITIONAL — 암이력+부분절제 → CONDITIONAL

> **검증 스텝**: p5AskMedical (분기점)
> **검증 내용**: 유방암 있고 부분절제 → 조건부 허용

| 조건 | 입력 Slots | 검증 |
|------|-----------|------|
| 스텝 p5AskMedical에서 | `breastCancerHistory`=true, `cancerSurgeryType`=부분, `implantPresence`=false, `fatSourceAvailability`=복부, `pastOps`=1회, `pastOpsSite`=가슴 (이전 Step p5AskDetail에서 수집) | `next_step().via` → **branching** |
| | | `protocolMode` → **CONDITIONAL** |

---

### #19. P5-BRANCH-CANCER-NOT-ALLOWED — 암이력+완전절제 → NOT_ALLOWED

> **검증 스텝**: p5AskMedical (분기점)
> **검증 내용**: 유방암 있고 완전절제 → 시술 불가

| 조건 | 입력 Slots | 검증 |
|------|-----------|------|
| 스텝 p5AskMedical에서 | `breastCancerHistory`=true, `cancerSurgeryType`=완전, `implantPresence`=true, `fatSourceAvailability`=복부, `implantCondition`=파손, `implantOriginHospital`=B성형외과, `pastOps`=1회, `pastOpsSite`=가슴 (이전 Step에서 수집) | `next_step().via` → **branching** |
| | | `protocolMode` → **NOT_ALLOWED** |

---

### #20. PROTOCOL-MODE-SKIP — protocolMode 시스템 관리

> **검증**: 어떤 상태에서든 protocolMode는 사용자에게 물어보지 않음

| 케이스 | 상태 | 검증 |
|--------|------|------|
| slot 비어있을 때 | persona=slimBody, step=p1CollectInfo, slots=없음 | `should_skip("protocolMode")` → **true** |
| slot 채워져있을 때 | persona=longDistance, step=p4Collect, protocolMode=FULL | `should_skip("protocolMode")` → **true** |

---

## 자동 로직 요약

### 자동 계산 (Auto-Compute)

| Slot | 조건 | 계산 방식 |
|------|------|----------|
| `bmi` | `bodyInfo` 수집 완료 | bodyInfo에서 키(cm)/몸무게(kg) 파싱 → kg/(m²) |
| `regionBucket` | `residenceCountry` 수집 완료 | ABROAD/해외/외국 → "ABROAD", 국내 → domesticDistrict로 S1~S6 매핑 |

### 조건부 스킵 (Conditional Skip)

| 스킵되는 Slot | 조건 | 설명 |
|-------------|------|------|
| `implantCondition` | `implantPresence`=false | 보형물 없으면 상태 불필요 |
| `implantOriginHospital` | `implantPresence`=false | 보형물 없으면 병원 불필요 |
| `domesticDistrict` | `residenceCountry`=ABROAD | 해외면 국내 지역 불필요 |
| `weightGainPlan` | `weightGainIntent`=false | 증량 의사 없으면 계획 불필요 |
| `nutritionConsult` | `weightGainIntent`=false | 증량 의사 없으면 영양상담 불필요 |
| `inbodyPhotoUpload` | `inbodyAvailable`=false | 인바디 없으면 업로드 불필요 |
| `pastOpsSite` | `pastOps` ∈ ["없음","없습니다","false","none","no","처음"] | 과거 시술 없으면 시술 부위 불필요 |

### 시스템 자동 설정 (System-Managed)

| Slot | 설정 시점 | 설명 |
|------|----------|------|
| `protocolMode` | 분기 규칙 평가 시 | STANDARD / LOW-FAT / SEMI-REMOTE / FULL / CONDITIONAL / NOT_ALLOWED |

### regionBucket 매핑

| regionBucket | 지역 | protocolMode |
|-------------|------|-------------|
| S1 | 서울 | STANDARD |
| S2 | 경기, 인천 | STANDARD |
| S3 | 대전, 세종, 충남, 충북, 충청 | SEMI-REMOTE |
| S4 | 부산, 대구, 울산, 경남, 경북 | SEMI-REMOTE |
| S5 | 광주, 전남, 전북, 전라 | SEMI-REMOTE |
| S6 | 강원, 제주 | SEMI-REMOTE |
| ABROAD | 해외 | FULL |

### P5 암이력 분기 조건

| breastCancerHistory | cancerSurgeryType | protocolMode |
|--------------------|-------------------|-------------|
| false | (무관) | STANDARD |
| true | 부분 | CONDITIONAL |
| true | 완전 | NOT_ALLOWED |

### P5 슬롯 분배 (Graph CHECKS 기준)

| Step | CHECKS 연결 CheckItem | 수집 조건 |
|------|---------------------|----------|
| **p5AskDetail** | breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite | **6개 모두 필수** (pastOpsSite는 pastOps 값에 따라 conditional skip) |
| **p5AskMedical** | implantCondition, implantOriginHospital | **2개 conditional** (implantPresence=true일 때만 수집) |

---

## 분기 규칙 커버리지 매트릭스

> 온톨로지의 **모든 BRANCHING_RULES + CONDITIONAL_SKIP_RULES + AUTO_COMPUTABLE_SLOTS**가 두 테스트 파일에서 커버됨을 보증합니다.

### BRANCHING_RULES (5개 분기점, 15개 규칙)

| # | 분기점 | 규칙 | protocolMode | test_scenarios.py | test_repl.py |
|---|--------|------|-------------|-------------------|-------------|
| 1 | p1InformSurgery | ruleBodyFatHigh (BMI≥23) | STANDARD | P1-STANDARD ✓ | p1std ✓ |
| 2 | p1InformSurgery | ruleBodyFatLow (BMI<23) | LOW-FAT | P1-LOWFAT ✓ | p1lf ✓, p1lf_nogain ✓, p1lf_athlete ✓ |
| 3 | p1InformSurgery | default | STANDARD | (P1-STANDARD에서 커버) | — |
| 4 | p2InformSurgery | upsellAccept=false | → p2InformInfoA | P2-LIPO-ONLY ✓ | p2a ✓ |
| 5 | p2InformSurgery | upsellAccept=true | → p2InformInfoB | P2-LIPO+TRANSFER ✓ | p2b_stem ✓, p2b_general ✓ |
| 6 | p2InformSurgery | default (lipoDefault) | → p2InformInfoA | — | — |
| 7 | p2InformInfoB | transferType=일반 | → p2Finalize | P2-LIPO+TRANSFER ✓ | p2b_general ✓ |
| 8 | p2InformInfoB | transferType=줄기세포 | → p2Finalize | P2-STEMCELL ✓ | p2b_stem ✓ |
| 9 | p2InformInfoB | default | → p2Finalize | — (edge case) | — |
| 10 | p4PreCollect | ruleRegionRemote (ABROAD) | FULL | P4-ABROAD ✓ | p4abroad ✓ |
| 11 | p4PreCollect | ruleRegionSemiRemote (≠S1,≠S2) | SEMI-REMOTE | P4-SEMIREMOTE ✓ | p4semi ✓, p4semi_s3 ✓ |
| 12 | p4PreCollect | default (S1/S2) | STANDARD | P4-STANDARD ✓ | p4std ✓ |
| 13 | p5AskMedical | ruleCancerNone (cancer=false) | STANDARD | P5-BRANCH-CANCER-NONE ✓ | p5_std ✓, p5_std_implant ✓ |
| 14 | p5AskMedical | ruleCancerConditional (cancer=true+부분) | CONDITIONAL | P5-BRANCH-CANCER-CONDITIONAL ✓, P5-CONDITIONAL-WALK ✓ | p5_conditional ✓ |
| 15 | p5AskMedical | ruleCancerNotAllowed (cancer=true+완전) | NOT_ALLOWED | P5-BRANCH-CANCER-NOT-ALLOWED ✓, P5-NOT-ALLOWED-WALK ✓ | p5_not_allowed ✓ |

### CONDITIONAL_SKIP_RULES (7개)

| # | 스킵 대상 | 조건 | test_scenarios.py | test_repl.py |
|---|----------|------|-------------------|-------------|
| 1 | implantCondition | implantPresence=false | P5-IMPLANT-SKIP ✓ | p5_std ✓, p5_conditional ✓ |
| 2 | implantOriginHospital | implantPresence=false | P5-IMPLANT-SKIP ✓ | p5_std ✓, p5_conditional ✓ |
| 3 | domesticDistrict | residenceCountry=ABROAD | P4-REGION-AUTOCALC ✓ | p4abroad ✓ |
| 4 | weightGainPlan | weightGainIntent=false | P1-SKIP-WEIGHTGAIN ✓ | p1std ✓, p1lf_nogain ✓ |
| 5 | nutritionConsult | weightGainIntent=false | P1-SKIP-WEIGHTGAIN ✓ | p1std ✓, p1lf_nogain ✓ |
| 6 | inbodyPhotoUpload | inbodyAvailable=false | P4-INBODY-SKIP ✓ | p4abroad ✓, p4semi_s3 ✓ |
| 7 | pastOpsSite | pastOps ∈ ["없음","없습니다","false","none","no","처음"] | P1-SKIP-PASTOPSSITE ✓ | p1std ✓, p1lf ✓, p1lf_nogain ✓, p1lf_athlete ✓, p2a ✓, p4abroad ✓, p4semi ✓, p4std ✓, p4semi_s3 ✓ |

### AUTO_COMPUTABLE_SLOTS (2개)

| # | Slot | 소스 | test_scenarios.py | test_repl.py |
|---|------|------|-------------------|-------------|
| 1 | bmi | bodyInfo → BMI | P1-STANDARD ✓, P1-LOWFAT ✓ | p1std ✓, p1lf ✓, p1lf_athlete ✓ |
| 2 | regionBucket | residenceCountry/domesticDistrict | P4-REGION-AUTOCALC ✓ | p4abroad ✓, p4semi ✓, p4std ✓, p4semi_s3 ✓ |

### SYSTEM_MANAGED_SLOTS (1개)

| # | Slot | test_scenarios.py | test_repl.py |
|---|------|-------------------|-------------|
| 1 | protocolMode | PROTOCOL-MODE-SKIP ✓ | (모든 분기 시나리오에서 암묵적 검증) |

---

## STEP_CHECKPOINT_REQUIREMENTS — Graph CHECKS 기준 (31개 Step)

> 각 Step에서 반드시 수집되어야 하는 CheckItem 목록. Graph의 `Step -[:CHECKS]-> CheckItem` 관계와 1:1 일치.
> AUTO_COMPUTABLE, SYSTEM_MANAGED, conditional skip 대상은 검증 시 별도 처리.

| 페르소나 | Step | 필수 슬롯 | 비고 |
|---------|------|----------|------|
| **P1** | p1CollectInfo | bodyInfo, bodyFat, bodyType, inbodyAvailable | |
| | p1AskLifestyle | activityPattern, exerciseLevel, dietPattern, weightGainIntent | |
| | p1AskDetail | fatSourceAvailability, pastOps, pastOpsSite | pastOpsSite conditional |
| | p1InformInfo | recoveryGuideline | nutritionConsult, weightGainPlan conditional |
| | p1Confirm | customerName, phoneNumber, surgeryWindow, recheckSchedule | |
| **P2** | p2PreCollect | basicInfo, bodyInfo, schedule, concernArea, medicalHistory | |
| | p2Collect | travelConstraint | bodyInfo, schedule 이전 Step에서 수집 |
| | p2AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance, jobIntensity | |
| | p2AskDetail | fatSourceAvailability, lipoArea, lipoGoal, riskFactor, pastOps | |
| | p2InformSurgery | planPreference, upsellAccept, concernSideEffect, costSensitivity | recoveryAllowance 이전 수집 |
| | p2InformInfoA | recoveryTimeline, lipoPlanDetail, costRange | |
| | p2InformInfoB | transferType, recoveryTimeline, graftExpectation, costRange, **transferPlanDetail** | |
| | p2Finalize | precheckRequired, visitSchedule, sameDayPossible, reservationIntent | |
| **P3** | p3Collect | bodyInfo, bodyFat, skinType, skinCondition | |
| | p3AskLifestyle | activityPattern, sunExposure, skincareRoutine, smoking | |
| | p3AskDetail | fatSourceAvailability, allergyHistory, pastOps, **botoxCycle**, **fillerRemaining**, **pastOpsSite** | |
| | p3AskSurgery | concernArea, desiredEffect, durabilityExpectation | |
| | p3Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | |
| **P4** | p4PreCollect | residenceCountry, visitPeriod, travelConstraint | domesticDistrict, regionBucket conditional |
| | p4Collect | bodyInfo, bodyFat, inbodyAvailable | inbodyPhotoUpload conditional |
| | p4AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance | |
| | p4AskDetail | fatSourceAvailability, pastOps, **pastOpsSite** | |
| | p4InformInfo | precheckTimeEstimate, bodyPhotoUpload, documentUpload | |
| | p4Confirm | surgeryWindow, depositReservation | |
| | p4Finalize | customerName, phoneNumber, aftercarePlan, followupSchedule | |
| **P5** | p5Collect | bodyInfo, bodyFat, bodyType | |
| | p5AskLifestyle | activityPattern, smoking, workConstraint, recoveryAllowance | |
| | p5AskDetail | breastCancerHistory, implantPresence, cancerSurgeryType, **fatSourceAvailability**, **pastOps**, **pastOpsSite** | 6개 CHECKS |
| | p5AskMedical | **implantCondition**, **implantOriginHospital** | 2개 conditional |
| | p5InformInfo | aftercarePlan, scarManagement, riskExplanationLevel | |
| | p5Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | |

> **굵은 글씨**: 이전 세션(Graph 정합성 검증)에서 추가/재배치된 슬롯
