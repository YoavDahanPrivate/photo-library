"""Display-only collapsing of HEIC/JPEG format pairs within the filtered results."""
def collapse_format_pairs(where,args):
    # Ineligible records get their own partition. Apply search first so a matching
    # JPEG is not hidden behind a HEIC that does not match the person's/date filters.
    partition="""m.phone,lower(substr(m.name,1,length(m.name)-length(m.extension))),
        m.taken,m.width,m.height,
        CASE WHEN m.kind='photo' AND m.taken IS NOT NULL AND m.taken!=''
          AND m.width>0 AND m.height>0 AND lower(m.extension) IN ('.heic','.jpg','.jpeg')
          THEN '' ELSE m.id END"""
    inner=f"""SELECT m.id,
        row_number() OVER (PARTITION BY {partition} ORDER BY lower(m.extension)!='.heic',m.id) rn,
        max(lower(m.extension)='.heic') OVER (PARTITION BY {partition}) has_heic,
        max(lower(m.extension) IN ('.jpg','.jpeg')) OVER (PARTITION BY {partition}) has_jpeg
        FROM media m WHERE {where}"""
    return "m.id IN (SELECT id FROM ("+inner+") WHERE NOT (has_heic AND has_jpeg) OR rn=1)",args
