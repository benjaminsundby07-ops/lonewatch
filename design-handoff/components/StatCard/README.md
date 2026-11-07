# StatCard

Kort med tittel, liten kurve, stort tall og valgfrie rader under. På oversikten: «Handlinger vurdert», «Røde varsler» og «Blokkert», med «Sluppet gjennom» som rad i det første.

**Du gir:** `title`, `value` (ferdig formatert), `rows` (`[{label, value}]`, kan være tom), `data`/`ghost`/`marks` for kurven og `color`.

- Kurvene er pynt uten akser, men formen ligger i `chartShapes` i datasettet og er også eksempeldata.
