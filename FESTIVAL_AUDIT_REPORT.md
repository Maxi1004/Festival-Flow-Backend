# Auditoría de festivales

Fecha de la auditoría: 2026-06-09

Fuentes:

- `C:\Users\Maxi\Downloads\FECHAS FESTIVALES 2025-2026.xlsx`
- Colección Firestore `festivals` consultada en modo de solo lectura
- `app/services/admin_festival_service.py`

## Resultado ejecutivo

```text
TOTAL_FILAS_EXCEL=1065
TOTAL_FILAS_VALIDAS=947
TOTAL_DUPLICADOS=542
TOTAL_FESTIVALES_UNICOS=405
```

`TOTAL_FILAS_EXCEL` cuenta filas con algún contenido. El libro tiene 5.236
filas físicas por formato residual, pero 4.171 están completamente vacías.

Los 947 registros válidos se reducen a 442 nombres normalizados y a 405
festivales reales después de fusionar 37 variantes de nombre confirmadas.
Por tanto, 542 filas válidas son repeticiones de un festival ya representado.

## Excel por hoja

| Hoja | Filas con contenido | Filas válidas | Ignoradas |
|---|---:|---:|---:|
| Festivals 2025 | 364 | 359 | 5 |
| Los Días Azules | 101 | 98 | 3 |
| Copia de Los Días Azules | 48 | 46 | 2 |
| AMILCAR Festivals 2025 | 304 | 301 | 3 |
| subvencionados ICAA | 140 | 99 | 41 |
| Listado festivales | 108 | 44 | 64 |
| **Total** | **1.065** | **947** | **118** |

Las 118 filas ignoradas son 64 filas auxiliares, 40 filas de secciones ICAA,
9 nombres inválidos y 5 encabezados. Entre los nombres inválidos hay URLs,
la nota “ciclo de Cine y Salud Mental...”, `Cyprus` y `2025`.

## Duplicados del Excel

- Duplicación por nombre exacto: 491 filas redundantes.
- Duplicación por nombre normalizado: 505 filas redundantes.
- Duplicación semántica confirmada: 542 filas redundantes.
- Festivales únicos finales: 405.

Ejemplos confirmados:

- `Festival de Málaga` = `Festival de Cine de Málaga`.
- `CANNES INTERNATIONAL FILM FESTIVAL` = `Festival de Cannes`.
- `IndieLisboa` = `IndieLisboa Film Festival`.
- `Alcances` = `Festival de Cine Documental Alcances`.
- `IBIZACINEFEST-Ibiza Independent Film Festival` = `Ibiza Cine Fest`.
- `Radiance Film Festival` es un error de escritura de `Raindance Film Festival`;
  comparte correo, URL y fechas.
- `Festival de Cine Comprometido Guadalajara` =
  `Festival de Cine Solidario de Guadalajara. FESCIGU`.
- `SEMINCI` = `Semana Internacional de Cine de Valladolid (SEMINCI)`.
- `Zinebi` = `International Festival of Documentary and Short Film of Bilbao –
  ZINEBI`.
- `Cinespaña Toulouse`, su nombre extendido y la fila “Documentary Official
  Competition” representan el mismo festival.

No se fusionaron secciones con su festival principal, por ejemplo
`Quinzaine des Cinéastes - Festival Cannes` o
`Semaine de la critique at Locarno Film Festival`.

## Firestore

- Documentos actuales: 491.
- Documentos válidos: 485.
- Festivales únicos normalizados: 412.
- Festivales únicos semánticos: 382.
- Documentos redundantes: 103, distribuidos en 95 grupos.
- Documentos auxiliares inválidos: 6.
- Festivales del Excel ausentes: 23.
- Festivales válidos ajenos al Excel: 0.

La reconciliación es exacta:

```text
382 existentes únicos + 23 faltantes = 405 festivales reales
485 válidos - 103 redundantes = 382 existentes únicos
491 totales - 485 válidos = 6 auxiliares inválidos
```

### Documentos auxiliares

Eliminar:

- `2cjHPlYhvItoNKjx3cXH`: URL de una noticia.
- `54u9EBSz3dyoU9Iumz00`: nombre `2025`.
- `ZjJLuZDd6fjDHK6nAZoW`: URL de una noticia.
- `hFdBSWF7VIl8C7hzrDkX`: nota “ciclo de Cine y Salud Mental...”.

Corregir o fusionar:

- `GmE5ns7qZ0XumDTMCiyj`: la URL usada como nombre corresponde a
  `Menorca Doc Fest`.
- `FURLwpmPfcNbYaU7VPhK`: `Cyprus` corresponde a la fila
  `16th International Short Film Festival of Cyprus`.

### Ejemplos de documentos para fusionar

- `F3Y92ZuZKsXyYCHdEiJj` con `uJkzXWfN19g8XnaSyh42`:
  BAFICI; conservar la copia con país, URL y fechas.
- `jdkDFbwtBEEtQakw5r2f` con `m9jzRWkvU0bTzNK1yWUk`:
  Bogotá International Film Festival.
- `DMuQUCUxicxQMgoIXxf9` con `LftxDtT0dZYwoJICtThI`:
  Chicago International Film Festival.
- `Hll0pJTLYFIVOYo9UwiK` con `Wz25Iu3JXD9FgGXXMRLV`:
  DOK Leipzig.
- `8Oo9U86oKUVsr7Ny03UV` con `1YKetDtSRNwDKmkmy6P7`:
  Berlinale.

Hay cuatro pares del mismo festival en ediciones distintas: CineHealth,
Festival de Huelva, Festival ÍCARO y FICINDIE. Si el modelo representa una
entidad festival, deben fusionarse y las ediciones pasar a una subcolección o
lista. Si cada documento representa una edición, no deben contarse como
festivales únicos.

El archivo `festival-audit.json` contiene los 95 grupos completos con IDs.

## Faltantes en Firestore

Los 23 festivales ausentes son:

1. 16th International Short Film Festival of Cyprus
2. Africa International Film Festival - AFRIFF
3. Astra Film International Documentary Film Festiva
4. Bergen International Film Festival
5. Brussels Independet Film Festival
6. CineGouna
7. CORTOGENIA
8. Doc Luanda
9. DOCKANEMA
10. Dublin International Film Festival
11. Espoo Ciné International Film Festival
12. Fespaco
13. Festival Nacional de Cortometrajes Plasencia Encorto
14. Festival Villa del Cine
15. Gijon IFF
16. Horcynus Festival
17. Jornadas Cinematográficas de Cartago (JCC)
18. Menorca Doc Fest
19. Rome International Film Festival
20. Singapore International Film Festival (SGIFF)
21. Transcinema Festival Internacional de Cine
22. Trieste Film Festival
23. Washington DC International Film Festival

## Estados

Estado actual de los 491 documentos:

```json
{
  "open": 15,
  "upcoming": 1,
  "closed": 255,
  "archived": 0,
  "unknown": 220,
  "total": 491
}
```

La suma coincide exactamente. Los seis documentos auxiliares están en
`UNKNOWN`. Tras excluirlos quedan 485 documentos y 214 `UNKNOWN`.

Si se conserva la copia más completa de cada festival, los 382 existentes
quedan provisionalmente así:

```json
{
  "open": 9,
  "upcoming": 1,
  "closed": 245,
  "archived": 0,
  "unknown": 127,
  "total": 382
}
```

Este segundo conteo requiere recalcular estados después de la fusión.

## Datos incompletos

- Documentos incompletos actuales: 261 de 491.
- Documentos casi vacíos: 146.
- Tras elegir la copia más completa por festival: 165 de 382 siguen
  incompletos y 56 siguen casi vacíos.

Campos ausentes después de fusionar:

- `opening_date`: 142.
- `deadline`: 127.
- `website`: 124.
- `event_date`: 97.
- `country`: 74.

## Fechas

El importador actual produce 56 errores de fecha:

- 39 son el marcador `-`, que debe convertirse a valor vacío.
- 17 son valores malformados repetidos en ocho festivales.

Normalización propuesta:

- `-`, `??`, `?`: guardar `""` y conservar el texto original en notas.
- `septiembre`, `octubre`, `julio`: no inventar día; guardar fecha vacía,
  mes/año separado si existe y marcar para revisión.
- `01 dic 2025 / 17 dic 2025`: guardar inicio `2025-12-01` y fin
  `2025-12-17`; el modelo actual necesita `event_end_date`.
- `October 9 – 16, 2025`: inicio `2025-10-09`, fin `2025-10-16`.
- `31/06/26`: fecha imposible; requiere corrección en la fuente.

Los errores explican la ausencia de CORTOGENIA, DOCKANEMA, Espoo Ciné,
Gijon IFF, Horcynus y Singapore International Film Festival.

## Fallos del importador

1. `AMILCAR Festivals 2025` no tiene un alias de encabezado en la primera
   celda: contiene el nombre FIDMarseille. `_find_header_row` no reconoce la
   hoja y omite sus 304 filas.
2. `Países` no está en `HEADER_ALIASES["country"]`. La hoja ICAA se importa
   sin país y crea copias casi vacías.
3. `-` se envía a `_normalize_date` y provoca el descarte de la fila completa.
4. Meses, intervalos y años de dos cifras no están soportados.
5. `_dedupe_key(name, country, edition_year)` separa el mismo festival cuando
   cambia el idioma del país, falta el país o cambia la edición.
6. La normalización no elimina años, ubicaciones entre paréntesis ni alias.
7. Una fila posterior puede sobrescribir datos buenos con celdas vacías.
8. `Conv. Abierta` y `Conv. Cerrada` no figuran en `STATUS_ALIASES`.

## Recomendaciones

1. Adoptar 405 como total maestro de festivales del libro auditado.
2. Separar `Festival` de `FestivalEdition`; no usar el año para identificar la
   entidad festival.
3. Crear `canonical_name`, `canonical_country` y un `festival_key` estable.
4. Mantener una tabla explícita de alias y exigir revisión humana para
   coincidencias difusas.
5. Fusionar los 95 grupos Firestore conservando el registro con más campos y
   completándolo con valores no vacíos de las demás copias.
6. Eliminar cuatro auxiliares y transformar los dos placeholders de Menorca y
   Cyprus.
7. Importar los 23 faltantes después de corregir encabezados y fechas.
8. No sobrescribir un valor existente con vacío, `-`, `False` o texto inválido.
9. Recalcular estados una sola vez después de la reconciliación y comprobar
   que la suma sea igual al total de entidades.

No se modificó ningún documento de Firestore durante esta auditoría.
