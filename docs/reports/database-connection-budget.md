# Database Connection Budget

Evidence code SHA: `53b10b896bb934298d1ca11571aa01f24f00a812`

The default Authority fleet is validated during API construction and again by
the database-backed readiness probe against PostgreSQL's actual
`max_connections`.

| Role | Instances | Max per instance | Fleet maximum |
|---|---:|---:|---:|
| API | 1 | 8 | 8 |
| Chapter Worker | 1 | 4 | 4 |
| Content Worker | 1 | 4 | 4 |
| Source Worker | 1 | 3 | 3 |
| MKAOS Worker | 1 | 3 | 3 |
| Book Worker | 1 | 3 | 3 |
| Outbox Worker | 1 | 2 | 2 |
| Maintenance Worker | 1 | 2 | 2 |
| **Application fleet** | **8** |  | **29** |

| Capacity component | Connections |
|---|---:|
| PostgreSQL `max_connections` | 100 |
| Management reserve | 10 |
| Migration reserve | 2 |
| Emergency reserve | 5 |
| Application capacity | 83 |
| Allocated application maximum | 29 |
| Remaining application headroom | 54 |

The one-shot migration pool maximum is 1 and is covered by the migration reserve.
Callback admission is part of API and dispatch is part of Chapter, so they do not
add separate container pools. Instance counts are explicit environment settings;
scaling a role without increasing its declared instance count makes readiness
fail rather than silently exceeding capacity.
