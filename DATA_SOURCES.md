# Data sources

One row per dataset. A dataset is not used until its **License** cell is filled
from the source's own page (quote it), or marked "unverified" with the reason.
Raw play-by-play stays local (`data/raw/` and the sibling cache are
gitignored); the repo publishes only derived, game-level results, the same
rule the playoff-series and contract-year studies follow.

| Dataset | URL | License (quoted) | Commercial use | Redistribution | Retrieved | Local file |
|---|---|---|---|---|---|---|
| Regular-season `PlayByPlayV3`, NBA 2023-24 to 2025-26 and WNBA 2024 to 2026 (4,546 games) | https://stats.nba.com/stats/playbyplayv3 (harvested by playbyplay-study) | unverified: NBA.com terms of use govern the underlying data; no explicit license on the endpoint. Not redistributed here | no (personal research) | no: raw rows stay local, derived results only | harvested by playbyplay-study, July to October 2026 | `../playbyplay-study/data/raw_pbp/*.parquet` (read in place) |
| Playoff `PlayByPlayV3` archives, NBA 2023-24 to 2025-26 and WNBA 2024, 2025 (`nbastatsv3_po_*`) | https://github.com/shufinskiy/nba_data | Repository: "Apache License 2.0" (GitHub license metadata). The rows themselves come from stats.nba.com, so NBA.com terms still govern the data: unverified | no (personal research) | no: kept in `data/raw/`, gitignored | October 19, 2026 | `data/raw/nbastatsv3_po_2023.tar.xz` and four more (sha256 in `data/raw_checksums.txt`) |
| pbpstats possession tables, same six regular seasons | built by playbyplay-study with the `pbpstats` library | `pbpstats` library: MIT (unverified for this note); data as above | no | no | October 2026 | `../playbyplay-study/data/possessions/*.parquet` |

## Notes

- Playoff archive coverage was checked against playoff-series-study's
  `LeagueGameLog` table on October 19, 2026: 82, 84, and 85 NBA games and 22
  and 24 WNBA games, equal game for game.
- WNBA 2026 playoffs are not in the archive (no `wnba_nbastatsv3_po_2026`
  file on October 19, 2026), and the NBA stats hosts are blocked from both of
  Chester's machines (stats hosts time out, cdn.nba.com returns 403). They
  join when either source opens.
