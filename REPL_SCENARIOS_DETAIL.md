# SC301 REPL 시나리오 상세 (test_repl.py 기준, 17개)

> 기준 파일: `test_repl.py` — TEST_SCENARIOS dict
> CheckItem 출처: Neo4j 그래프 (Step → CHECKS → CheckItem)
> 마지막 검증: 2026-02-21 — Graph CHECKS 관계와 100% 정합성 확인 완료

---

## 목차

| # | 키 | 시나리오 | 페르소나 | 경로 (Step 수) | 분기 | 엑셀 근거 |
|---|-----|---------|---------|--------------|------|----------|
| 1 | `p1std` | P1 STANDARD | slimBody | 6 | BMI≥23 → STANDARD | §1.1~1.4 |
| 2 | `p1lf` | P1 LOW-FAT (증량 희망) | slimBody | 6 | BMI<23 → LOW-FAT | §1.1~1.4 |
| 3 | `p1lf_nogain` | P1 LOW-FAT (증량 거부) | slimBody | 6 | BMI<23 → LOW-FAT, skip | §1.1~1.4 |
| 4 | `p1lf_athlete` | P1 LOW-FAT (운동선수) | slimBody | 6 | BMI<23 → LOW-FAT | **§1.5** |
| 5 | `p2a` | P2 흡입 단독 | lipoCustomer | 7 | upsellAccept=false | §2.1~2.4 |
| 6 | `p2b_stem` | P2 흡입+줄기세포 | lipoCustomer | 7 | upsellAccept=true, 줄기세포 | §2.1~2.4 |
| 7 | `p2b_general` | P2 흡입+일반이식 | lipoCustomer | 7 | upsellAccept=true, 일반 | §2.1~2.4 |
| 8 | `p3` | P3 피부시술 | skinTreatment | 6 | 분기 없음 | §3.1~3.4 |
| 9 | `p3_filler_exp` | P3 필러이력자 | skinTreatment | 6 | 분기 없음 | **§3.5** |
| 10 | `p4abroad` | P4 해외 (FULL) | longDistance | 8 | ABROAD | §4.1~4.4 |
| 11 | `p4semi` | P4 부산 (SEMI-REMOTE) | longDistance | 8 | S4 | §4.1~4.4 |
| 12 | `p4std` | P4 서울 (STANDARD) | longDistance | 8 | S1 | §4.1~4.4 |
| 13 | `p4semi_s3` | P4 대전 (SEMI-REMOTE) | longDistance | 8 | S3 | **§4.4** |
| 14 | `p5_std` | P5 STANDARD (암-/보형물-) | revisionFatigue | 7 | cancer=false | §5.1~5.4 |
| 15 | `p5_std_implant` | P5 STANDARD (암-/보형물+) | revisionFatigue | 7 | cancer=false, implant | §5.1~5.4 |
| 16 | `p5_conditional` | P5 CONDITIONAL (부분절제) | revisionFatigue | 7 | cancer=true+부분 | §5.1~5.4 |
| 17 | `p5_not_allowed` | P5 NOT_ALLOWED (전절제) | revisionFatigue | 7 | cancer=true+완전 | §5.1~5.4 |

---

## 1. `p1std` — P1 슬림바디 STANDARD (BMI≥23)

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI=26.1 → ruleBodyFatHigh → STANDARD
> **스킵**: weightGainPlan, nutritionConsult (weightGainIntent=false)

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=slimBody, Scenario=scenLowFat | "안녕하세요, 가슴에 줄기세포 지방이식 하고 싶은데 체지방이 충분한지 상담받고 싶어요." |
| 1 | p1CollectInfo | bodyInfo, bodyFat, bodyType, inbodyAvailable | `bodyInfo`=165cm 71kg, `bodyFat`=30, `bodyType`=보통, `inbodyAvailable`=true | "키 165cm이고 몸무게 71kg이에요. 체지방률은 30%정도 되고, 보통 체형이에요. 인바디는 있어요." |
| 2 | p1AskLifestyle | activityPattern, exerciseLevel, dietPattern, weightGainIntent | `activityPattern`=주3회 운동, `exerciseLevel`=중간, `dietPattern`=불규칙, `weightGainIntent`=false | "주 3회 운동하고 있어요. 운동 강도는 중간이고 식단은 불규칙해요. 체중 증량은 필요 없어요." |
| 3 | p1AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=복부, 허벅지, `pastOps`=없음, `pastOpsSite`=없음 | "복부랑 허벅지에서 지방 채취 가능하고요, 가슴 관련 시술 이력은 없습니다." |
| — | p1InformSurgery | **(없음)** | ▶ `protocolMode`=STANDARD (자동) | *(자동 전이: ruleBodyFatHigh, BMI=26.1)* |
| 4 | p1InformInfo | ~~weightGainPlan~~, ~~nutritionConsult~~, recoveryGuideline | `recoveryGuideline`=2주 압박복 착용 | "회복 가이드라인은 2주 압박복 착용으로 할게요." |
| 5 | p1Confirm | customerName, phoneNumber, surgeryWindow, recheckSchedule | `customerName`=김지현, `phoneNumber`=010-9876-5432, `surgeryWindow`=다음달, `recheckSchedule`=2주 후 | "김지현입니다. 010-9876-5432에요. 다음달에 수술 가능하고, 재확인은 2주 후에 할게요." |

---

## 2. `p1lf` — P1 슬림바디 LOW-FAT (BMI<23, 증량 희망)

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI=20.2 → ruleBodyFatLow → LOW-FAT
> **스킵 없음**: weightGainIntent=true이므로 weightGainPlan, nutritionConsult 수집

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=slimBody, Scenario=scenLowFat | "마른 체형인데 가슴에 지방이식 하고 싶어요. 채취할 지방이 충분할지 걱정이에요." |
| 1 | p1CollectInfo | bodyInfo, bodyFat, bodyType, inbodyAvailable | `bodyInfo`=165cm 55kg, `bodyFat`=18, `bodyType`=마른체형, `inbodyAvailable`=false | "165cm에 55kg이에요. 체지방 18%이고 마른체형입니다. 인바디는 없어요." |
| 2 | p1AskLifestyle | activityPattern, exerciseLevel, dietPattern, weightGainIntent | `activityPattern`=거의 안함, `exerciseLevel`=낮음, `dietPattern`=소식, `weightGainIntent`=true | "운동은 거의 안 해요. 소식하는 편이고 가슴 지방이식을 위해 체중 좀 늘리고 싶어요." |
| 3 | p1AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=허벅지 소량, `pastOps`=없음, `pastOpsSite`=없음 | "허벅지에 지방이 소량 있고, 가슴 시술 경험은 없습니다." |
| — | p1InformSurgery | **(없음)** | ▶ `protocolMode`=LOW-FAT (자동) | *(자동 전이: ruleBodyFatLow, BMI=20.2)* |
| 4 | p1InformInfo | weightGainPlan, nutritionConsult, recoveryGuideline | `weightGainPlan`=한달 3kg 증량 목표, `nutritionConsult`=영양사 상담 희망, `recoveryGuideline`=3주 압박복 | "한달에 3kg 증량 목표로 하고, 영양사 상담도 받고 싶어요. 회복은 3주 압박복이요." |
| 5 | p1Confirm | customerName, phoneNumber, surgeryWindow, recheckSchedule | `customerName`=이수진, `phoneNumber`=010-1111-2222, `surgeryWindow`=2개월 후, `recheckSchedule`=1개월 후 | "이수진이에요. 010-1111-2222입니다. 2개월 후에 수술하고 1개월 후에 재방문할게요." |

---

## 3. `p1lf_nogain` — P1 슬림바디 LOW-FAT (BMI<23, 증량 거부)

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI=19.7 → ruleBodyFatLow → LOW-FAT
> **스킵**: weightGainPlan, nutritionConsult (weightGainIntent=false)

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=slimBody, Scenario=scenLowFat | "가슴에 줄기세포 지방이식 받고 싶은데요, 마른편이라 지방이 부족할 수도 있다고 하더라고요." |
| 1 | p1CollectInfo | bodyInfo, bodyFat, bodyType, inbodyAvailable | `bodyInfo`=158cm 49kg, `bodyFat`=17, `bodyType`=마른편, `inbodyAvailable`=true | "158cm 49kg이에요. 체지방 17%이고 마른편이에요. 인바디 있어요." |
| 2 | p1AskLifestyle | activityPattern, exerciseLevel, dietPattern, weightGainIntent | `activityPattern`=필라테스 주2회, `exerciseLevel`=낮음, `dietPattern`=규칙적, `weightGainIntent`=false | "필라테스 주2회 해요. 식단은 규칙적이고 체중 증량은 안 할 거예요." |
| 3 | p1AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=허벅지 안쪽 소량, `pastOps`=없음, `pastOpsSite`=없음 | "허벅지 안쪽에 지방 소량이요. 가슴 시술은 처음입니다." |
| — | p1InformSurgery | **(없음)** | ▶ `protocolMode`=LOW-FAT (자동) | *(자동 전이: ruleBodyFatLow, BMI=19.7)* |
| 4 | p1InformInfo | ~~weightGainPlan~~, ~~nutritionConsult~~, recoveryGuideline | `recoveryGuideline`=2주 압박복 | "회복은 2주 압박복으로 하겠습니다." |
| 5 | p1Confirm | customerName, phoneNumber, surgeryWindow, recheckSchedule | `customerName`=박서연, `phoneNumber`=010-3333-4444, `surgeryWindow`=3주 후, `recheckSchedule`=2주 후 | "박서연이에요. 연락처는 010-3333-4444예요. 3주 후에 수술하고 2주 후 재확인할게요." |

---

## 4. `p1lf_athlete` — P1 슬림바디 LOW-FAT (운동선수 배경) *(추가)*

> **경로**: p1CollectInfo → p1AskLifestyle → p1AskDetail → p1InformSurgery → p1InformInfo → p1Confirm
> **분기**: BMI=19.5 → ruleBodyFatLow → LOW-FAT
> **스킵 없음**: weightGainIntent=true
> **엑셀 근거**: §1.5 운동선수/피트니스 식별 질문 — 보디빌더, 낮은 체지방률(12%), 고단백 식단

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=slimBody, Scenario=scenLowFat | "피트니스 대회 준비하면서 체지방이 많이 줄었는데, 대회 끝나고 가슴에 지방이식 받고 싶어요. 체지방이 부족할까 걱정이에요." |
| 1 | p1CollectInfo | bodyInfo, bodyFat, bodyType, inbodyAvailable | `bodyInfo`=168cm 55kg, `bodyFat`=12, `bodyType`=마른 근육질, `inbodyAvailable`=true | "168cm 55kg이에요. 체지방률은 12%이고 마른 근육질이에요. 인바디 데이터 있어요." |
| 2 | p1AskLifestyle | activityPattern, exerciseLevel, dietPattern, weightGainIntent | `activityPattern`=매일 웨이트 트레이닝, `exerciseLevel`=매우 높음, `dietPattern`=고단백 식단, `weightGainIntent`=true | "매일 웨이트 트레이닝해요. 운동 강도 매우 높고 고단백 식단 유지 중이에요. 대회 끝나면 가슴 지방이식 위해 체중 증량 할 수 있어요." |
| 3 | p1AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=옆구리 소량, `pastOps`=없음, `pastOpsSite`=없음 | "옆구리에 약간 지방이 있고요, 복부는 거의 없어요. 시술 경험 없습니다." |
| — | p1InformSurgery | **(없음)** | ▶ `protocolMode`=LOW-FAT (자동) | *(자동 전이: ruleBodyFatLow, BMI=19.5)* |
| 4 | p1InformInfo | weightGainPlan, nutritionConsult, recoveryGuideline | `weightGainPlan`=2개월 5kg 증량 목표, `nutritionConsult`=스포츠 영양사 상담 희망, `recoveryGuideline`=4주 압박복 | "대회 후 2개월간 5kg 증량 목표로 하고 스포츠 영양사 상담도 받고 싶어요. 회복은 4주 압박복이요." |
| 5 | p1Confirm | customerName, phoneNumber, surgeryWindow, recheckSchedule | `customerName`=최서윤, `phoneNumber`=010-4321-8765, `surgeryWindow`=3개월 후, `recheckSchedule`=한달 뒤 | "최서윤이에요. 010-4321-8765에요. 대회 끝나고 3개월 후에 가슴 수술하고, 한달 뒤에 재확인할게요." |

---

## 5. `p2a` — P2 지방흡입 단독 (upsellAccept=false)

> **경로**: p2PreCollect → p2Collect → p2AskLifestyle → p2AskDetail → p2InformSurgery → **p2InformInfoA** → p2Finalize
> **분기**: upsellAccept=false → p2InformInfoA (흡입 단독)

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=lipoCustomer, Scenario=scenLipoGraft | "지방흡입 상담 받으려고요. 복부 지방흡입 후 가슴 이식도 가능한지 알아보고 있어요." |
| 1 | p2PreCollect | basicInfo, bodyInfo, concernArea, medicalHistory, schedule | `bodyInfo`=163cm 62kg, `schedule`=다음주 화요일, `concernArea`=가슴 볼륨, `medicalHistory`=없음, `basicInfo`=서지영 010-1234-5678 | "163cm 62kg이고 다음주 화요일에 상담 가능해요. 가슴 볼륨이 고민이고 병력은 없습니다. 서지영 010-1234-5678입니다." |
| 2 | p2Collect | bodyInfo, schedule, travelConstraint | `travelConstraint`=없음 | "교통편 제약은 없어요." |
| 3 | p2AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance, jobIntensity | `activityPattern`=주3회 필라테스, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주, `jobIntensity`=사무직 | "주3회 필라테스하고 운동 강도 중간이에요. 비흡연이고 회복 기간 2주 가능해요. 사무직입니다." |
| 4 | p2AskDetail | fatSourceAvailability, lipoArea, lipoGoal, riskFactor, pastOps | `fatSourceAvailability`=복부 충분, `lipoArea`=복부, 옆구리, `lipoGoal`=가슴 볼륨 업, `riskFactor`=없음, `pastOps`=없음 | "복부에 지방 충분하고 복부 옆구리 흡입 원해요. 가슴 볼륨 업이 목표고 위험요소 없어요. 과거 시술 없습니다." |
| 5 | p2InformSurgery | planPreference, upsellAccept, concernSideEffect, costSensitivity, recoveryAllowance | `planPreference`=흡입 단독, **`upsellAccept`=false**, `concernSideEffect`=멍, `costSensitivity`=중간, `recoveryAllowance`=2주 | "일단 흡입 단독으로 하고 싶어요. 가슴 이식은 나중에 고려할게요. 멍이 좀 걱정되고 비용은 중간 정도면 좋겠어요." |
| 6 | p2InformInfoA | recoveryTimeline, lipoPlanDetail, costRange | `recoveryTimeline`=2주 압박복, `lipoPlanDetail`=복부 전체 흡입, `costRange`=300-500만원 | "회복은 2주 압박복, 복부 전체 흡입으로 진행하고 비용은 300-500만원 사이면 좋겠어요." |
| 7 | p2Finalize | precheckRequired, visitSchedule, sameDayPossible, reservationIntent | `precheckRequired`=true, `visitSchedule`=다음주 목요일, `sameDayPossible`=false, `reservationIntent`=true | "사전검사 필요하고 다음주 목요일에 방문할게요. 당일 수술은 안 되고 예약 의사 있습니다." |

---

## 6. `p2b_stem` — P2 흡입+이식, 줄기세포

> **경로**: p2PreCollect → p2Collect → p2AskLifestyle → p2AskDetail → p2InformSurgery → **p2InformInfoB** → p2Finalize
> **분기**: upsellAccept=true → p2InformInfoB, transferType=줄기세포 → p2Finalize

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=lipoCustomer, Scenario=scenLipoGraft | "지방흡입이랑 가슴에 줄기세포 지방이식을 같이 하고 싶어서요." |
| 1 | p2PreCollect | basicInfo, bodyInfo, concernArea, medicalHistory, schedule | `bodyInfo`=168cm 65kg, `schedule`=이번주 금요일, `concernArea`=가슴 볼륨, `medicalHistory`=없음, `basicInfo`=이영희 010-5678-1234 | "168cm 65kg입니다. 이번주 금요일 가능하고 가슴 볼륨이 고민이에요. 병력 없고 이영희 010-5678-1234예요." |
| 2 | p2Collect | bodyInfo, schedule, travelConstraint | `travelConstraint`=없음 | "이동 제약 없습니다." |
| 3 | p2AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance, jobIntensity | `activityPattern`=주2회, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=3주, `jobIntensity`=프리랜서 | "주 2회 운동하고 중간 강도예요. 담배 안 피우고 3주 회복 가능합니다. 프리랜서에요." |
| 4 | p2AskDetail | fatSourceAvailability, lipoArea, lipoGoal, riskFactor, pastOps | `fatSourceAvailability`=허벅지, `lipoArea`=허벅지 안쪽, `lipoGoal`=가슴 이식용 지방 확보, `riskFactor`=없음, `pastOps`=없음 | "허벅지에서 지방 채취하고 허벅지 안쪽 흡입 원해요. 가슴 이식용 지방 확보가 목적이고 위험요소 없어요. 과거 시술 없음." |
| 5 | p2InformSurgery | planPreference, upsellAccept, concernSideEffect, costSensitivity, recoveryAllowance | `planPreference`=흡입+가슴이식, **`upsellAccept`=true**, `concernSideEffect`=부기, `costSensitivity`=낮음, `recoveryAllowance`=3주 | "흡입이랑 가슴 이식 같이 하고 싶어요. 부기가 걱정되고 비용은 좀 높아도 괜찮아요." |
| 6 | p2InformInfoB | transferType, transferPlanDetail, recoveryTimeline, graftExpectation, costRange | **`transferType`=줄기세포**, `transferPlanDetail`=줄기세포 이식 가슴 볼륨 보충, `recoveryTimeline`=4주 회복, `graftExpectation`=자연스러운 가슴 볼륨, `costRange`=800-1200만원 | "줄기세포 이식으로 하고 싶어요. 줄기세포 이식으로 가슴 볼륨 보충 계획이에요. 회복 4주 예상하고 자연스러운 가슴 볼륨 원해요. 800-1200만원 예산이에요." |
| 7 | p2Finalize | precheckRequired, visitSchedule, sameDayPossible, reservationIntent | `precheckRequired`=true, `visitSchedule`=다음주 월요일, `sameDayPossible`=true, `reservationIntent`=true | "사전검사 하고 다음주 월요일에 방문합니다. 당일 수술도 가능하면 좋겠고 예약할게요." |

---

## 7. `p2b_general` — P2 흡입+이식, 일반

> **경로**: p2PreCollect → p2Collect → p2AskLifestyle → p2AskDetail → p2InformSurgery → **p2InformInfoB** → p2Finalize
> **분기**: upsellAccept=true → p2InformInfoB, transferType=일반 → p2Finalize

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=lipoCustomer, Scenario=scenLipoGraft | "복부 지방흡입하고 가슴에 일반 지방이식도 같이 하고 싶어요." |
| 1 | p2PreCollect | basicInfo, bodyInfo, concernArea, medicalHistory, schedule | `bodyInfo`=160cm 58kg, `schedule`=이번주 토요일, `concernArea`=가슴 볼륨, `medicalHistory`=없음, `basicInfo`=한소희 010-2222-3333 | "160cm 58kg이에요. 이번주 토요일 가능하고 가슴 볼륨이 고민입니다. 병력 없고 한소희 010-2222-3333이에요." |
| 2 | p2Collect | bodyInfo, schedule, travelConstraint | `travelConstraint`=없음 | "교통편 문제없어요." |
| 3 | p2AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance, jobIntensity | `activityPattern`=주4회 수영, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주, `jobIntensity`=교사 | "주4회 수영하고 강도 중간이에요. 비흡연이고 2주 회복 가능합니다. 교사에요." |
| 4 | p2AskDetail | fatSourceAvailability, lipoArea, lipoGoal, riskFactor, pastOps | `fatSourceAvailability`=복부 넉넉, `lipoArea`=복부, `lipoGoal`=가슴 볼륨 업, `riskFactor`=없음, `pastOps`=없음 | "복부에 지방 넉넉하고 복부 흡입 원합니다. 가슴 볼륨 업이 목표고 특별한 위험요소 없어요. 시술 이력 없음." |
| 5 | p2InformSurgery | planPreference, upsellAccept, concernSideEffect, costSensitivity, recoveryAllowance | `planPreference`=흡입+가슴이식, **`upsellAccept`=true**, `concernSideEffect`=붓기, `costSensitivity`=중간, `recoveryAllowance`=2주 | "가슴 이식도 함께 하고 싶어요. 비용은 적당하면 좋겠고 붓기가 걱정이에요." |
| 6 | p2InformInfoB | transferType, transferPlanDetail, recoveryTimeline, graftExpectation, costRange | **`transferType`=일반**, `transferPlanDetail`=일반 이식 가슴 볼륨 보충, `recoveryTimeline`=2주 회복, `graftExpectation`=자연스러운 가슴 결과, `costRange`=500-700만원 | "일반 이식으로 할게요. 일반 이식으로 가슴 볼륨 보충할 계획이에요. 회복 2주 예상하고 자연스러운 가슴 결과 원해요. 500-700만원 예산입니다." |
| 7 | p2Finalize | precheckRequired, visitSchedule, sameDayPossible, reservationIntent | `precheckRequired`=true, `visitSchedule`=다음주 수요일, `sameDayPossible`=false, `reservationIntent`=true | "사전검사 하고 다음주 수요일 방문합니다. 당일 수술은 안 되고 예약할게요." |

---

## 8. `p3` — P3 피부시술 가슴성형 전후 피부관리 (선형)

> **경로**: p3Collect → p3AskLifestyle → p3AskDetail → p3AskSurgery → p3InformSugery → p3Confirm
> **분기**: 없음 (선형 플로우)

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=skinTreatment, Scenario=scenAntiAging | "가슴 줄기세포 지방이식을 고려하고 있는데, 수술 전후 가슴 피부 탄력이랑 흉터 관리도 같이 상담받고 싶어요." |
| 1 | p3Collect | bodyInfo, bodyFat, skinType, skinCondition | `bodyInfo`=162cm 50kg, `bodyFat`=22, `skinType`=건성, `skinCondition`=가슴 부위 탄력 저하, 흉터 우려 | "162cm 50kg이고 체지방 22%예요. 건성 피부에 가슴 부위 탄력 저하가 고민이에요." |
| 2 | p3AskLifestyle | activityPattern, sunExposure, skincareRoutine, smoking | `activityPattern`=요가 주2회, `sunExposure`=높음, `skincareRoutine`=기초 화장품만 사용, `smoking`=false | "요가 주2회 하고요. 야외 근무라 자외선 노출이 많아요. 기초 화장품만 쓰고 담배는 안 펴요." |
| 3 | p3AskDetail | fatSourceAvailability, allergyHistory, pastOps, botoxCycle, fillerRemaining, pastOpsSite | `fatSourceAvailability`=허벅지, `fillerRemaining`=false, `allergyHistory`=없음, `pastOps`=없음, `pastOpsSite`=없음, `botoxCycle`=없음 | "허벅지 지방 있고 필러 잔여물 없어요. 알레르기 없고 가슴 관련 보톡스 경험은 없어요. 과거 시술 없고 보톡스 주기도 없습니다." |
| 4 | p3AskSurgery | concernArea, desiredEffect, durabilityExpectation | `concernArea`=가슴 피부 탄력, 수술 후 흉터, `desiredEffect`=자연스러운 가슴 라인 + 피부결 개선, `durabilityExpectation`=1년 이상 | "가슴 지방이식 후 피부 탄력 개선이 고민이에요. 자연스러운 가슴 라인과 피부결 효과 원하고 1년 이상 지속되면 좋겠어요." |
| — | p3InformSugery | **(없음)** | — | *(자동 전이)* |
| 5 | p3Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | `customerName`=최윤아, `phoneNumber`=010-4444-5555, `surgeryWindow`=이번달 내, `visitSchedule`=다음주 수요일, `procedurePlan`=줄기세포 지방이식 + 피부 탄력 시술 | "최윤아예요. 010-4444-5555입니다. 이번달 내에 하고 싶고 다음주 수요일 방문 가능해요. 줄기세포 지방이식 + 피부 탄력 시술 계획이에요." |

---

## 9. `p3_filler_exp` — P3 피부시술 가슴성형 고려 중 피부관리 이력자 *(추가)*

> **경로**: p3Collect → p3AskLifestyle → p3AskDetail → p3AskSurgery → p3InformSugery → p3Confirm
> **분기**: 없음 (선형)
> **엑셀 근거**: §3.5 과거 시술 경험 식별 질문 — 필러/보톡스 다회 경험자, 필러 잔여물 있음

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=skinTreatment, Scenario=scenAntiAging | "가슴 줄기세포 지방이식 전에 피부 탄력 관리를 하고 싶어요. 필러는 해봤는데 더 오래 유지되는 방법이 있을까요?" |
| 1 | p3Collect | bodyInfo, bodyFat, skinType, skinCondition | `bodyInfo`=167cm 54kg, `bodyFat`=20, `skinType`=복합성, `skinCondition`=가슴 피부 탄력 저하, 수술 흉터 우려 | "167cm 54kg이고 체지방 20%예요. 복합성 피부에 팔자주름이랑 볼 꺼짐이 고민이에요." |
| 2 | p3AskLifestyle | activityPattern, sunExposure, skincareRoutine, smoking | `activityPattern`=필라테스 주3회, `sunExposure`=낮음, `skincareRoutine`=스킨케어 루틴 있음, `smoking`=false | "필라테스 주 3회 해요. 실내 근무라 자외선 노출 적은 편이고 스킨케어 루틴이 있어요. 비흡연이에요." |
| 3 | p3AskDetail | fatSourceAvailability, allergyHistory, pastOps, botoxCycle, fillerRemaining, pastOpsSite | `fatSourceAvailability`=허벅지, **`fillerRemaining`=약간 남아있음**, `allergyHistory`=없음, `pastOps`=필러 5회, 보톡스 4회, `pastOpsSite`=팔자주름, 이마, `botoxCycle`=4개월 주기 | "허벅지에 지방 있고 필러 잔여물이 아직 좀 남아있어요. 알레르기 없고 필러 5회, 보톡스 4회 맞았어요. 팔자주름이랑 이마에 맞았고 4개월 주기로 했었어요." |
| 4 | p3AskSurgery | concernArea, desiredEffect, durabilityExpectation | `concernArea`=가슴 피부 탄력, 수술 후 흉터 관리, `desiredEffect`=자연스러운 가슴 라인 + 피부 탄력, `durabilityExpectation`=최소 2년 | "팔자주름 개선이 제일 급하고 볼 볼륨도 채우고 싶어요. 동안 느낌으로 자연스러운 효과 원하고 최소 2년은 유지되면 좋겠어요." |
| — | p3InformSugery | **(없음)** | — | *(자동 전이)* |
| 5 | p3Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | `customerName`=김예진, `phoneNumber`=010-7654-3210, `surgeryWindow`=다음달 초, `visitSchedule`=이번주 금요일, `procedurePlan`=가슴 줄기세포 지방이식 + 피부 탄력 시술 | "김예진이에요. 010-7654-3210이요. 다음달 초에 하고 싶고 이번주 금요일 방문 가능해요. 줄기세포 지방이식이랑 리프팅 결합으로요." |

---

## 10. `p4abroad` — P4 원거리 해외 (FULL)

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: ABROAD → ruleRegionRemote → FULL
> **스킵**: domesticDistrict (ABROAD), inbodyPhotoUpload (inbodyAvailable=false)
> **자동 계산**: regionBucket=ABROAD

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=longDistance, Scenario=scenRemote | "해외에 살고 있는데 한국에서 가슴 줄기세포 지방이식 받으려고요. 원거리 상담 가능할까요?" |
| 1 | p4PreCollect | residenceCountry, ~~domesticDistrict~~, ~~regionBucket~~, visitPeriod, travelConstraint | `residenceCountry`=ABROAD, `visitPeriod`=2주, `travelConstraint`=비자 필요 | "해외에 살고 있어요. 2주 정도 한국 방문 가능하고 비자가 필요해요." |
| 2 | p4Collect | bodyInfo, bodyFat, inbodyAvailable, ~~inbodyPhotoUpload~~ | `bodyInfo`=163cm 55kg, `bodyFat`=24, `inbodyAvailable`=false | "163cm 55kg이고 체지방 24%예요. 인바디 데이터는 없어요." |
| 3 | p4AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance | `activityPattern`=주3회 요가, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=3주 | "주 3회 요가하고 중간 강도예요. 담배 안 피고 3주 회복 가능합니다." |
| 4 | p4AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=복부, `pastOps`=없음, `pastOpsSite`=없음 | "복부에서 지방 채취 가능하고 가슴 관련 시술 이력 없어요." |
| — | p4InformSurgery | **(없음)** | — | *(자동 전이)* |
| 5 | p4InformInfo | precheckTimeEstimate, bodyPhotoUpload, documentUpload | `precheckTimeEstimate`=2시간, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | "사전검사 2시간 예상하고 체형 사진이랑 서류 업로드했어요." |
| 6 | p4Confirm | surgeryWindow, depositReservation | `surgeryWindow`=다음달, `depositReservation`=true | "다음달에 수술하고 보증금 예약할게요." |
| 7 | p4Finalize | customerName, phoneNumber, aftercarePlan, followupSchedule | `customerName`=정하나, `phoneNumber`=010-6666-7777, `aftercarePlan`=현지 병원 연계, `followupSchedule`=수술 후 2주 원격 상담 | "정하나에요. 010-6666-7777입니다. 현지 병원 연계로 사후관리하고 수술 후 2주 원격 상담 받을게요." |

---

## 11. `p4semi` — P4 원거리 부산 (SEMI-REMOTE)

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: 부산 → S4 → ruleRegionSemiRemote → SEMI-REMOTE
> **자동 계산**: regionBucket=S4

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=longDistance, Scenario=scenRemote | "부산에서 서울까지 가야 하는데 가슴 줄기세포 지방이식 원거리 상담 가능할까요?" |
| 1 | p4PreCollect | residenceCountry, domesticDistrict, ~~regionBucket~~, visitPeriod, travelConstraint | `residenceCountry`=한국, `domesticDistrict`=부산, `visitPeriod`=3일, `travelConstraint`=KTX 이용 | "한국 부산에 살고 있어요. 3일 정도 서울 방문 가능하고 KTX 이용합니다." |
| 2 | p4Collect | bodyInfo, bodyFat, inbodyAvailable, inbodyPhotoUpload | `bodyInfo`=162cm 56kg, `bodyFat`=25, `inbodyAvailable`=true, `inbodyPhotoUpload`=uploaded | "162cm 56kg이고 체지방 25%예요. 인바디 있고 사진도 업로드했어요." |
| 3 | p4AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance | `activityPattern`=주3회 필라테스, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주 | "주3회 필라테스 다니고 중간 강도예요. 비흡연이고 2주 회복 가능합니다." |
| 4 | p4AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=복부, 허벅지, `pastOps`=없음, `pastOpsSite`=없음 | "복부 허벅지에서 채취 가능. 가슴 시술 이력 없습니다." |
| — | p4InformSurgery | **(없음)** | — | *(자동 전이)* |
| 5 | p4InformInfo | precheckTimeEstimate, bodyPhotoUpload, documentUpload | `precheckTimeEstimate`=1시간, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | "사전검사 1시간이면 되고 사진 서류 다 올렸어요." |
| 6 | p4Confirm | surgeryWindow, depositReservation | `surgeryWindow`=이번달, `depositReservation`=true | "이번달에 수술하고 보증금 입금합니다." |
| 7 | p4Finalize | customerName, phoneNumber, aftercarePlan, followupSchedule | `customerName`=윤다혜, `phoneNumber`=010-8888-9999, `aftercarePlan`=지역 병원 연계, `followupSchedule`=1주 후 재방문 | "윤다혜예요. 010-8888-9999입니다. 지역 병원 연계 사후관리하고 1주 후 재방문할게요." |

---

## 12. `p4std` — P4 원거리 서울 (STANDARD)

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: 서울 → S1 → default → STANDARD
> **자동 계산**: regionBucket=S1

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=longDistance, Scenario=scenRemote | "서울 사는데 가슴 줄기세포 지방이식 상담 받으려고요. 내원 상담이 가능한지 궁금해요." |
| 1 | p4PreCollect | residenceCountry, domesticDistrict, ~~regionBucket~~, visitPeriod, travelConstraint | `residenceCountry`=한국, `domesticDistrict`=서울, `visitPeriod`=수시 가능, `travelConstraint`=없음 | "서울에 살고 있어요. 수시로 방문 가능하고 교통 제약 없습니다." |
| 2 | p4Collect | bodyInfo, bodyFat, inbodyAvailable, inbodyPhotoUpload | `bodyInfo`=160cm 52kg, `bodyFat`=23, `inbodyAvailable`=true, `inbodyPhotoUpload`=uploaded | "160cm 52kg이고 체지방 23%예요. 인바디 있고 사진 업로드했어요." |
| 3 | p4AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance | `activityPattern`=주3회 러닝, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=2주 | "주3회 러닝하고 중간 강도예요. 비흡연이고 2주 회복 가능합니다." |
| 4 | p4AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=복부 충분, `pastOps`=없음, `pastOpsSite`=없음 | "복부 지방 충분하고 가슴 관련 시술 이력 없어요." |
| — | p4InformSurgery | **(없음)** | — | *(자동 전이)* |
| 5 | p4InformInfo | precheckTimeEstimate, bodyPhotoUpload, documentUpload | `precheckTimeEstimate`=30분, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | "사전검사 30분이면 되고 사진 서류 준비됐어요." |
| 6 | p4Confirm | surgeryWindow, depositReservation | `surgeryWindow`=이번주, `depositReservation`=true | "이번주에 수술하고 보증금 납부하겠습니다." |
| 7 | p4Finalize | customerName, phoneNumber, aftercarePlan, followupSchedule | `customerName`=윤서아, `phoneNumber`=010-5555-6666, `aftercarePlan`=직접 내원, `followupSchedule`=1주 후 내원 | "윤서아예요. 010-5555-6666입니다. 직접 내원 사후관리하고 1주 후 내원할게요." |

---

## 13. `p4semi_s3` — P4 원거리 대전 (SEMI-REMOTE S3) *(추가)*

> **경로**: p4PreCollect → p4Collect → p4AskLifestyle → p4AskDetail → p4InformSurgery → p4InformInfo → p4Confirm → p4Finalize
> **분기**: 대전 → S3 → ruleRegionSemiRemote → SEMI-REMOTE
> **자동 계산**: regionBucket=S3
> **엑셀 근거**: §4.4 Step 1 권역 식별 — S3(충청) 권역 커버

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=longDistance, Scenario=scenRemote | "대전에서 사는데 가슴 줄기세포 지방이식 때문에 서울 내원이 부담돼요. 원거리 상담 가능한가요?" |
| 1 | p4PreCollect | residenceCountry, domesticDistrict, ~~regionBucket~~, visitPeriod, travelConstraint | `residenceCountry`=한국, `domesticDistrict`=대전, `visitPeriod`=2일, `travelConstraint`=KTX 이용 | "한국 대전에 살고 있어요. 주말 이용해서 2일 정도 서울 방문 가능하고 KTX로 이동합니다." |
| 2 | p4Collect | bodyInfo, bodyFat, inbodyAvailable, ~~inbodyPhotoUpload~~ | `bodyInfo`=160cm 53kg, `bodyFat`=22, `inbodyAvailable`=false | "160cm 53kg이고 체지방 22%예요. 인바디 없어요." |
| 3 | p4AskLifestyle | activityPattern, exerciseLevel, smoking, recoveryAllowance | `activityPattern`=주2회 수영, `exerciseLevel`=중간, `smoking`=false, `recoveryAllowance`=1주 | "주2회 수영하고 중간 강도예요. 비흡연이고 1주 회복 가능합니다." |
| 4 | p4AskDetail | fatSourceAvailability, pastOps, pastOpsSite | `fatSourceAvailability`=허벅지, `pastOps`=없음, `pastOpsSite`=없음 | "허벅지에서 지방 채취 가능하고 가슴 시술 이력 없습니다." |
| — | p4InformSurgery | **(없음)** | — | *(자동 전이)* |
| 5 | p4InformInfo | precheckTimeEstimate, bodyPhotoUpload, documentUpload | `precheckTimeEstimate`=1시간, `bodyPhotoUpload`=uploaded, `documentUpload`=uploaded | "사전검사 1시간이면 되고 사진이랑 서류 업로드했어요." |
| 6 | p4Confirm | surgeryWindow, depositReservation | `surgeryWindow`=다음주, `depositReservation`=true | "다음주에 수술하고 보증금 예약합니다." |
| 7 | p4Finalize | customerName, phoneNumber, aftercarePlan, followupSchedule | `customerName`=장예린, `phoneNumber`=010-3456-7890, `aftercarePlan`=대전 로컬 병원 연계, `followupSchedule`=2주 후 사진 원격 상담 | "장예린이에요. 010-3456-7890입니다. 대전 로컬 병원 연계 사후관리하고 2주 후 사진 원격 상담 받을게요." |

---

## 14. `p5_std` — P5 재수술 STANDARD (유방암 없음, 보형물 없음)

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → p5AskMedical → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=false → ruleCancerNone → STANDARD (분기점: p5AskMedical 이후)
> **스킵**: implantCondition, implantOriginHospital (implantPresence=false → p5AskMedical 슬롯 전체 스킵)
> **Graph 정합**: p5AskDetail에 6개 CHECKS (breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite), p5AskMedical에 2개 CHECKS (implantCondition, implantOriginHospital)

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=revisionFatigue, Scenario=scenRevision | "이전에 했던 시술 결과가 불만족스러워서 재수술 상담 받고 싶어요." |
| 1 | p5Collect | bodyInfo, bodyFat, bodyType | `bodyInfo`=160cm 55kg, `bodyFat`=24, `bodyType`=보통 | "160cm 55kg이고 체지방 24%예요. 보통 체형이에요." |
| 2 | p5AskLifestyle | activityPattern, smoking, workConstraint, recoveryAllowance | `activityPattern`=가끔 산책, `smoking`=false, `workConstraint`=사무직, `recoveryAllowance`=2주 | "가끔 산책하고 비흡연이에요. 사무직이고 2주 회복 가능해요." |
| 3 | p5AskDetail | breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite | `breastCancerHistory`=false, `implantPresence`=false, `cancerSurgeryType`=해당없음, `fatSourceAvailability`=복부, `pastOps`=가슴 확대 1회, `pastOpsSite`=가슴 | "유방암 이력 없어요. 보형물도 없습니다. 암 수술은 해당없어요. 복부 지방 있고 가슴 확대 1회 했었어요. 가슴 부위였어요." |
| 4 | p5AskMedical | ~~implantCondition~~, ~~implantOriginHospital~~ | *(빈 슬롯 — 보형물 없으므로 스킵)* | "보형물 관련은 해당없습니다." |
| — | p5InformSurgery | **(없음)** | ▶ `protocolMode`=STANDARD (자동) | *(자동 전이: ruleCancerNone)* |
| 5 | p5InformInfo | aftercarePlan, scarManagement, riskExplanationLevel | `aftercarePlan`=정기 검진, `scarManagement`=실리콘 시트, `riskExplanationLevel`=상세 | "정기 검진으로 사후관리하고 실리콘 시트로 흉터 관리할게요. 위험성 상세히 설명해주세요." |
| 6 | p5Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | `customerName`=강미래, `phoneNumber`=010-7777-8888, `surgeryWindow`=다음달, `visitSchedule`=다음주 금요일, `procedurePlan`=자가조직 재건 | "강미래에요. 010-7777-8888입니다. 다음달 수술하고 다음주 금요일에 방문할게요. 자가조직 재건으로 계획합니다." |

---

## 15. `p5_std_implant` — P5 재수술 STANDARD (유방암 없음, 보형물 있음)

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → **p5AskMedical** → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=false → ruleCancerNone → STANDARD
> **스킵 없음**: implantPresence=true → implantCondition, implantOriginHospital 수집 필수

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=revisionFatigue, Scenario=scenRevision | "보형물 넣었는데 구축이 와서 재수술 알아보고 있어요." |
| 1 | p5Collect | bodyInfo, bodyFat, bodyType | `bodyInfo`=163cm 58kg, `bodyFat`=26, `bodyType`=보통 | "163cm 58kg이고 체지방 26%예요. 보통 체형입니다." |
| 2 | p5AskLifestyle | activityPattern, smoking, workConstraint, recoveryAllowance | `activityPattern`=주2회 걷기, `smoking`=false, `workConstraint`=재택근무, `recoveryAllowance`=3주 | "주2회 걷기 운동하고 비흡연이에요. 재택근무라 제약 없고 3주 회복 가능해요." |
| 3 | p5AskDetail | breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite | `breastCancerHistory`=false, `implantPresence`=true, `cancerSurgeryType`=해당없음, `fatSourceAvailability`=복부, `pastOps`=가슴 확대 2회, `pastOpsSite`=가슴 | "유방암 이력 없어요. 보형물 있습니다. 암 수술은 해당없어요. 복부 지방 있고 가슴 확대 2회 했었어요. 가슴 부위에요." |
| 4 | p5AskMedical | **implantCondition**, **implantOriginHospital** | `implantCondition`=구축, `implantOriginHospital`=A성형외과 | "보형물 상태는 구축이 왔어요. 이전에 A성형외과에서 했습니다." |
| — | p5InformSurgery | **(없음)** | ▶ `protocolMode`=STANDARD (자동) | *(자동 전이: ruleCancerNone)* |
| 5 | p5InformInfo | aftercarePlan, scarManagement, riskExplanationLevel | `aftercarePlan`=월 1회 검진, `scarManagement`=압박밴드, `riskExplanationLevel`=기본 | "월 1회 검진으로 사후관리하고 압박밴드로 흉터 관리할게요. 위험성 기본 설명이면 돼요." |
| 6 | p5Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | `customerName`=노은지, `phoneNumber`=010-1212-3434, `surgeryWindow`=2개월 후, `visitSchedule`=다음주 화요일, `procedurePlan`=보형물 교체 | "노은지에요. 010-1212-3434입니다. 2개월 후 수술하고 다음주 화요일 방문할게요. 보형물 교체로 진행합니다." |

---

## 16. `p5_conditional` — P5 재수술 CONDITIONAL (유방암+부분절제)

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → p5AskMedical → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=true + cancerSurgeryType=부분 → ruleCancerConditional → CONDITIONAL
> **스킵**: implantCondition, implantOriginHospital (implantPresence=false)

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=revisionFatigue, Scenario=scenRevision | "유방암 수술 후에 재건 상담을 받고 싶어서요. 부분절제를 했었어요." |
| 1 | p5Collect | bodyInfo, bodyFat, bodyType | `bodyInfo`=155cm 52kg, `bodyFat`=22, `bodyType`=마른편 | "155cm 52kg이고 체지방 22%예요. 마른편이에요." |
| 2 | p5AskLifestyle | activityPattern, smoking, workConstraint, recoveryAllowance | `activityPattern`=산책 위주, `smoking`=false, `workConstraint`=사무직, `recoveryAllowance`=4주 | "산책 위주로 운동하고 비흡연이에요. 사무직이고 4주 회복 가능합니다." |
| 3 | p5AskDetail | breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite | **`breastCancerHistory`=true**, `implantPresence`=false, **`cancerSurgeryType`=부분**, `fatSourceAvailability`=허벅지, `pastOps`=유방 재건 1회, `pastOpsSite`=가슴 | "유방암 이력이 있어요. 부분절제 수술 받았습니다. 보형물은 없어요. 허벅지 지방 있고 유방 재건 1회 했었어요. 가슴 부위입니다." |
| 4 | p5AskMedical | ~~implantCondition~~, ~~implantOriginHospital~~ | *(빈 슬롯 — 보형물 없으므로 스킵)* | "보형물 관련은 해당없어요." |
| — | p5InformSurgery | **(없음)** | ▶ `protocolMode`=CONDITIONAL (자동) | *(자동 전이: ruleCancerConditional)* |
| 5 | p5InformInfo | aftercarePlan, scarManagement, riskExplanationLevel | `aftercarePlan`=주치의 협진, `scarManagement`=실리콘 시트, `riskExplanationLevel`=상세 | "주치의 협진으로 사후관리하고 실리콘 시트 사용할게요. 위험성 상세히 알고 싶어요." |
| 6 | p5Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | `customerName`=오수연, `phoneNumber`=010-5656-7878, `surgeryWindow`=3개월 후, `visitSchedule`=다음주 목요일, `procedurePlan`=자가조직 재건 | "오수연이에요. 010-5656-7878입니다. 3개월 후 수술 예정이고 다음주 목요일에 방문할게요. 자가조직 재건으로요." |

---

## 17. `p5_not_allowed` — P5 재수술 NOT_ALLOWED (유방암+전절제)

> **경로**: p5Collect → p5AskLifestyle → **p5AskDetail** → **p5AskMedical** → p5InformSurgery → p5InformInfo → p5Confirm
> **분기**: breastCancerHistory=true + cancerSurgeryType=완전 → ruleCancerNotAllowed → NOT_ALLOWED
> **스킵 없음**: implantPresence=true → implantCondition, implantOriginHospital 수집 필수

| 순서 | Step | CheckItems (Graph) | 추출 Slot → 값 | 사용자 발화 |
|:----:|------|-------------------|---------------|-----------|
| 0 | *(인사/고민)* | — | ▶ Persona=revisionFatigue, Scenario=scenRevision | "유방암으로 전절제 수술을 받았는데 가슴 재건이 가능한지 상담받고 싶어요." |
| 1 | p5Collect | bodyInfo, bodyFat, bodyType | `bodyInfo`=157cm 50kg, `bodyFat`=20, `bodyType`=마른편 | "157cm 50kg이고 체지방 20%예요. 마른편이에요." |
| 2 | p5AskLifestyle | activityPattern, smoking, workConstraint, recoveryAllowance | `activityPattern`=거의 안함, `smoking`=false, `workConstraint`=주부, `recoveryAllowance`=2주 | "운동은 거의 안 하고 비흡연이에요. 주부이고 2주 회복 가능해요." |
| 3 | p5AskDetail | breastCancerHistory, cancerSurgeryType, fatSourceAvailability, implantPresence, pastOps, pastOpsSite | **`breastCancerHistory`=true**, `implantPresence`=true, **`cancerSurgeryType`=완전**, `fatSourceAvailability`=복부, `pastOps`=가슴 수술 3회, `pastOpsSite`=가슴 | "유방암 이력 있어요. 전절제 수술 받았습니다. 보형물도 있어요. 복부 지방 있고 가슴 수술 3회 했어요. 가슴 부위예요." |
| 4 | p5AskMedical | **implantCondition**, **implantOriginHospital** | `implantCondition`=파손, `implantOriginHospital`=B성형외과 | "보형물 상태는 파손이에요. B성형외과에서 했습니다." |
| — | p5InformSurgery | **(없음)** | ▶ `protocolMode`=NOT_ALLOWED (자동) | *(자동 전이: ruleCancerNotAllowed)* |
| 5 | p5InformInfo | aftercarePlan, scarManagement, riskExplanationLevel | `aftercarePlan`=종합 사후관리, `scarManagement`=레이저 흉터 치료, `riskExplanationLevel`=상세 | "종합 사후관리 원하고 레이저 흉터 치료할게요. 위험성 상세 설명 부탁드려요." |
| 6 | p5Confirm | customerName, phoneNumber, surgeryWindow, visitSchedule, procedurePlan | `customerName`=임소정, `phoneNumber`=010-9090-1010, `surgeryWindow`=상담 후 결정, `visitSchedule`=다음주 월요일, `procedurePlan`=대안 시술 상담 | "임소정이에요. 010-9090-1010입니다. 상담 후 결정할게요. 다음주 월요일에 방문하고 대안 시술 상담으로요." |

---

## 엑셀 판단기준 커버리지 요약

| 엑셀 섹션 | 내용 | 커버하는 시나리오 | 커버 수준 |
|----------|------|-----------------|----------|
| §1.1~1.4 | P1 기본 식별/분기/스킵 | p1std, p1lf, p1lf_nogain | 100% |
| **§1.5** | P1 운동선수/피트니스 배경 | **p1lf_athlete** | 100% |
| §2.1~2.4 | P2 기본 식별/분기(흡입/이식) | p2a, p2b_stem, p2b_general | 100% |
| §3.1~3.4 | P3 기본 식별/선형 | p3 | 100% |
| **§3.5** | P3 과거 시술(필러/보톡스) 이력자 | **p3_filler_exp** | 100% |
| §4.1~4.3 | P4 기본 식별/해외/국내 | p4abroad, p4semi, p4std | 100% |
| **§4.4** | P4 Step 1 권역 식별 (S3 추가) | **p4semi_s3** | 100% |
| §5.1~5.4 | P5 기본 식별/분기/스킵 | p5_std, p5_std_implant, p5_conditional, p5_not_allowed | 100% |

---

## 범례

| 표기 | 의미 |
|------|------|
| **순서 0** | 챗봇 인사("어떤 상담이 필요하신가요?")에 대한 사용자의 초기 고민 발화 → 페르소나/시나리오 추론 |
| ~~항목~~ | 조건부 스킵됨 (해당 시나리오에서 수집하지 않음) |
| **(없음)** | 해당 Step에 CheckItem이 없음 (inform 단계) |
| **굵은 값** | 분기 결정에 핵심이 되는 Slot 값 |
| ▶ | 시스템 자동 설정 (사용자 입력 아님) |
| *(자동 전이)* | CheckItem 없어 사용자 발화 불필요, 바로 다음 Step으로 이동 |
| *(추가)* | 이번 세션에서 추가된 시나리오 (엑셀 판단기준 기반) |
