# Error report

## Metrics

| Type | Gold | Predicted | P exact | R exact | F1 exact | P overlap | R overlap | F1 overlap |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PERSON | 93 | 92 | 0.978 | 0.968 | 0.973 | 0.978 | 0.968 | 0.973 |
| EMAIL | 38 | 37 | 1.000 | 0.974 | 0.987 | 1.000 | 0.974 | 0.987 |
| PHONE | 30 | 30 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ADDRESS | 11 | 11 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| DATE_OF_BIRTH | 6 | 6 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| IBAN | 8 | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| IP_ADDRESS | 6 | 6 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 |
| CUSTOMER_ID | 16 | 16 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ORGANIZATION | 8 | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| **micro avg** | 216 | 214 | 0.986 | 0.977 | 0.981 | 0.986 | 0.977 | 0.981 |

| Non-personal item | Count | Tagged as PII | Recognized as non-PII |
|---|---:|---:|---:|
| AMOUNT | 10 | 0 | 0 |
| CITY | 12 | 2 | 0 |
| COMPANY_VAT_ID | 4 | 0 | 0 |
| INVOICE_NUMBER | 18 | 0 | 0 |
| ISSUE_DATE | 9 | 0 | 0 |
| MESSAGE_DATE | 13 | 0 | 0 |
| ORDER_NUMBER | 5 | 0 | 0 |
| PRODUCT_CODE | 3 | 0 | 0 |
| ROLE_DISPLAY_NAME | 2 | 0 | 1 |
| SALUTATION | 2 | 0 | 0 |
| TICKET_ID | 9 | 0 | 0 |
| TIMESTAMP | 37 | 0 | 0 |
| VERSION_STRING | 10 | 1 | 0 |
| non-personal ADDRESS | 6 | 0 | 6 |
| non-personal EMAIL | 12 | 0 | 12 |
| non-personal IBAN | 4 | 0 | 4 |
| non-personal ORGANIZATION | 36 | 0 | 35 |
| **total** | 192 | 3 | 58 |

| Clustering (B-cubed) | Mentions | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| all gold PII mentions (missed = singleton) | 216 | 0.991 | 0.907 | 0.947 |
| detected gold PII mentions | 211 | 0.991 | 0.948 | 0.969 |

Gold PII entities: 15; predicted clusters: 23.

## Missed PII (5 gold spans with no overlapping prediction of the same type)

| Type | Document | Gold text | Predicted instead | Context |
|---|---|---|---|---|
| EMAIL | chats.jsonl:4:messages.2.text | n.shevchuk [at] karpaty-food.example | - |  write to n.shevchuk@karpaty-food.example or **[n.shevchuk [at] karpaty-food.example]**, not to the info box. |
| IP_ADDRESS | tickets.jsonl:6:body | 2001:db8:4a::17 | - | cted; the requests come from 192.0.2.100 and **[2001:db8:4a::17]**. Could you whitelist them? ⏎  ⏎ Cheers, ⏎ Alex Wri |
| PERSON | chats.jsonl:1:messages.0.text | dmytro | - | hi its **[dmytro]**, cant open my invoices |
| PERSON | chats.jsonl:1:messages.5.text | DMYTRO MELNYK | - | also the invoice must be on **[DMYTRO MELNYK]** like in my passport |
| PERSON | chats.jsonl:6:messages.2.text | Radim | - | info@tatra-logistics.example pls. our IT guy **[Radim]** has the details |

## False positives (3 predicted PII spans with no overlapping gold span of the same type)

| Type | Document | Text | Rule | Overlaps | Context |
|---|---|---|---|---|---|
| IP_ADDRESS | chats.jsonl:6:messages.2.text | 10.2.3.4 | ipv4 | VERSION_STRING | great, thx. we are on **[10.2.3.4]** everywhere btw. receipt to info@tatra-logist |
| PERSON | crm_export.csv:5:city | Martin | gazetteer-first | CITY | **[Martin]** |
| PERSON | crm_export.csv:11:city | Martin | gazetteer-first | CITY | **[Martin]** |

## Boundary differences (0 overlapping same-type pairs that are not exact)

| Type | Document | Gold | Predicted | Rule |
|---|---|---|---|---|

## Clustering: gold entities split over several predicted clusters

| Gold entity | Predicted clusters (mentions) |
|---|---|
| P01 | E1: (0905) 013-389, +421 905 013 389, 07.09.1966, 0905013389, 203.0.113.73, Alexander Kovalenko (+9 more) / E19: Коваленка / E22: Oleksandr |
| P02 | E2: +380505116155, 050 511 61 55, C-24592, Oleksandr Bondarenko, oleksandr.bondarenko@karpaty-food.example / E18: Олександре |
| P07 | E9: +380 67 564 13 95, 067 564 13 95, 198.51.100.195, C-28289, Dima, Dmytro (+8 more) / E21: 16 листопада 1978 |
| P13 | E7: +421 948 809 570, 0948 809 570, 0948/809 570, C-21395, Michal, Michal Varga (+2 more) / E20: Vargom |
| P15 | E16: Marek, Marek Bielik, SK4899010000001718227824, marek.bielik@mail.example / E12: Štúrova 66/A, 811 02 Bratislava |

## Clustering: predicted clusters that mix gold entities

| Predicted cluster | Gold entities (mentions) |
|---|---|
| E12 | P10: 0944978480, 18. novembra 1972, 18.11.1972, 81482, Bieliková, C-81482 (+6 more) / P15: Štúrova 66/A, 811 02 Bratislava |
