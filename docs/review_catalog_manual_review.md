# 기존 리뷰 상품 51개와 새 PC 카탈로그 수동 대조

기준일: 2026-09-19. 원본은 `data/review_summaries.json`, 대상은 `data/parts_list_modify.xlsx`의 제조사·모델명이며 적재 키는 `db/seed_pc_parts_specs.py`의 `product_type:brand:model` 규칙으로 확인했다. 이름 유사도만으로 리뷰를 이전하지 않는다. 용량·키트 구성·세대·접미사가 다르면 별도 상품으로 취급한다.

`total_reviews`의 36,700건은 JSON의 상품별 **합성 집계값 합계**다. 개별 리뷰 36,700행을 새 DB에 재기록한 수치가 아니다. 현재 연결된 상품은 **23/51**, 해당 집계 합계는 **17,270/36,700**, 저장 대상 요약은 **69개**다. 나머지 **28개 상품·19,430건 집계**는 의도적으로 연결하지 않았다.

이번 추가 확정: `fractal-design-north` → `case:프랙탈-디자인:north`. 제조사 번역만 다르고 모델 `North`가 같으며, 대상 카탈로그에는 `North XL`이 별도로 존재한다. 이 상품의 집계 944건과 요약 3개가 새 키로 연결된다.

## 연결하지 않은 28개

| 기존 키 | 새 카탈로그에서 확인한 근접 항목 / 보류 이유 |
| --- | --- |
| `amd-ryzen-7-7700` | `Ryzen 7 7700X`는 다른 모델. |
| `amd-ryzen-5-5600` | `Ryzen 5 7600`은 다른 세대·모델. |
| `asus-prime-b760m-a-wifi` | `PRIME B760M-K`, MSI `PRO B760M-A DDR4 II`는 다른 제품. |
| `asus-rog-strix-z790-e-gaming-wifi` | 근접한 ASUS ROG 보드는 칩셋·모델이 다름. |
| `msi-mag-b760-tomahawk-wifi` | `MAG B650/Z890 TOMAHAWK WIFI`는 칩셋이 다름. |
| `asrock-b860m-pro-rs` | `B760M/B650M PRO RS`는 칩셋이 다름. |
| `msi-mag-b850-tomahawk-wifi` | `MAG B650/Z890 TOMAHAWK WIFI`는 칩셋이 다름. |
| `samsung-ddr5-5600-32gb-2x16` | 새 카탈로그의 삼성 `DDR5-5600 (32GB)`는 단일 모듈. 16GB×2 키트로 확인되지 않음. |
| `g-skill-trident-z5-rgb-ddr5-6000-cl30-32gb-2x16` | 근접 키트는 `32GB x 2`로 용량 구성이 다름. |
| `g-skill-flare-x5-ddr5-6000-cl36-32gb-2x16` | 근접 G.SKILL 키트는 라인업·CL·용량이 다름. |
| `samsung-ddr4-3200-16gb-2x8` | 새 카탈로그의 삼성 `DDR4-3200 (16GB)`는 16GB×1. |
| `g-skill-ripjaws-v-ddr4-3600-32gb-2x16` | 근접 Ripjaws V는 DDR4-3200 CL16, 16GB×2. |
| `nvidia-geforce-rtx-4070-ti-super` | `RTX 4070 SUPER` 및 `RTX 5070 Ti`는 다른 GPU. |
| `samsung-990-pro-1tb` | 새 `990 PRO`는 1/2/4TB를 한 상품 모델로 기록. 1TB SKU/변형이 분리·확인되지 않음. |
| `samsung-990-pro-2tb` | 같은 이유. 1TB와 2TB 리뷰를 한 상품에 섞지 않음. |
| `wd-black-sn770-1tb` | 새 `WD_BLACK SN770`은 250GB~2TB 모델군. 1TB 변형이 분리·확인되지 않음. `SN770M`은 별개. |
| `crucial-mx500-1tb` | 근접 `BX500`, `T500`은 다른 제품군. |
| `corsair-rm650e` | 새 카탈로그에 동일 출력의 RM650e 없음. |
| `corsair-rm750e` | 새 `RM750e ATX 3.1`은 세대/리비전 일치가 확인되지 않음. |
| `corsair-rm850e` | 새 `RM850e ATX 3.1`은 세대/리비전 일치가 확인되지 않음. |
| `msi-mpg-a1000g-pcie5` | 새 `MEG AI1300P`, `MAG A750GL`은 다른 시리즈·용량. |
| `corsair-sf750` | 새 카탈로그에 동일 SFX 모델 없음. |
| `nzxt-h5-flow` | 새 `H6/H9 Flow`는 다른 케이스. |
| `cooler-master-nr200p-max` | 새 `MasterBox NR200P V2`는 다른 모델/구성. |
| `asus-prime-ap201` | 새 카탈로그에 동일 케이스 없음. |
| `noctua-nh-d15` | 새 `NH-D15 G2`는 다른 세대. |
| `arctic-liquid-freezer-iii-360` | 새 `Liquid Freezer III Pro 360`은 Pro 접미사가 다른 모델. |
| `deepcool-ak400` | 새 `AG400 G2`는 다른 시리즈·세대. |

나머지를 늘리려면 동일 SKU를 새 카탈로그에 별도 추가하거나, 제조사 부품 번호·용량·리비전으로 같은 제품임을 확인한 뒤 `data/review_catalog_map.csv` 한 행만 연결한다. 특히 SSD 모델군에 용량별 리뷰를 합치려면 카탈로그의 변형 단위와 리뷰 연결 단위를 먼저 설계해야 한다.
