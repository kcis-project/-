"""
build_site_structured.py
members_structured.csv → 인원 디렉토리 웹페이지(index.html) 생성
컬럼: 이름, 학과, 부/복수공, 직종, 경력1, 경력 1 기간, ...(x8), 더낸활동, 자격증, 현직자여부
"""

import csv, json, os, re, sys

BASE     = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE, 'directory_site', 'index.html')

DEPT_RE = re.compile(r'\((\d{2}|\d{4})\)')


def parse_year(text):
    m = DEPT_RE.search(text or '')
    return m.group(1) if m else ''


def extract_company(text):
    """경력 텍스트에서 회사명만 추출 (Wikipedia 툴팁용)"""
    line = (text or '').split('\n')[0].strip()
    part = line.split('|')[0].strip()
    part = re.sub(r"['\`]?\d{2,4}[.\-\/~]\S*", '', part)
    part = re.sub(r'주식회사|유한회사|\(주\)|\(유\)|㈜|㈔', '', part)
    part = part.rstrip('.,| ').strip()
    return (part or text)[:40]


def clean_item(text):
    return text.strip().lstrip('•·▢∙*※-▪▫ \t').strip()


def parse_row(row):
    name = row[0].strip() if row else ''
    if not name or len(name) < 2 or len(name) > 12:
        return None
    if re.search(r'^\d', name) or name in ('이름', '성명'):
        return None

    dept         = row[1].strip() if len(row) > 1 else ''
    double_major = row[2].strip() if len(row) > 2 else ''
    job_type     = row[3].strip() if len(row) > 3 else ''
    year         = parse_year(dept)

    # 경력 1~8 (col 4~19, 2열씩)
    experiences = []
    for i in range(8):
        ci, pi = 4 + i * 2, 5 + i * 2
        exp_text = row[ci].strip() if ci < len(row) and row[ci] else ''
        period   = row[pi].strip() if pi < len(row) and row[pi] else ''
        if not exp_text:
            continue
        company = extract_company(exp_text)
        display = exp_text + (' · ' + period if period else '')
        experiences.append({'company': company, 'text': display})

    # 더낸활동 (col 20)
    act_raw = row[20].strip() if len(row) > 20 else ''
    activities = []
    for item in re.split(r'\s*\|\s*', act_raw):
        c = clean_item(item)
        if c and len(c) > 2:
            activities.append(c)

    # 자격증 (col 21)
    cert_raw = row[21].strip() if len(row) > 21 else ''
    certs = []
    for item in re.split(r'\s*[|,]\s*', cert_raw):
        c = clean_item(item)
        if c and len(c) > 1:
            certs.append(c)

    # 현직자 여부 (col 22)
    is_current = row[22].strip().upper() == 'Y' if len(row) > 22 and row[22] else False

    dept_display = dept + (f' / {double_major}' if double_major else '')
    current = experiences[0]['company'] if experiences else ''

    return {
        'name':        name,
        'dept':        dept_display,
        'year':        year,
        'job_type':    job_type,
        'current':     current,
        'is_current':  is_current,
        'experiences': experiences[:8],
        'education':   [],
        'awards':      activities[:8],
        'certs':       certs,
        'etc':         activities[8:],
        'linkedin':    '',
    }


def load_persons(csv_path):
    persons = []
    with open(csv_path, encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader, None)          # 헤더 스킵
        for row in reader:
            if not row:
                continue
            p = parse_row(row)
            if p:
                persons.append(p)
    persons.sort(key=lambda x: x['name'])
    return persons


def main():
    sys.path.insert(0, BASE)
    from build_site import HTML                 # CSS + JS + MODAL_HTML 재활용

    # CSV 경로 결정
    if len(sys.argv) > 1:
        csv_path = os.path.abspath(sys.argv[1])
    else:
        csv_path = os.path.join(BASE, 'members_structured.csv')

    if not os.path.exists(csv_path):
        # 바탕화면도 확인
        desktop = os.path.join(os.path.expanduser('~'), 'Desktop', 'members_structured.csv')
        if os.path.exists(desktop):
            csv_path = desktop
        else:
            print(f'[오류] 파일을 찾을 수 없습니다: {csv_path}')
            print('파일을 linkedin-scraper 폴더에 넣거나 경로를 인자로 전달하세요.')
            print('  예) python build_site_structured.py members_structured.csv')
            sys.exit(1)

    print(f'파싱 중: {csv_path}')
    persons = load_persons(csv_path)
    print(f'  → {len(persons)}명 완료')

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    html = HTML.replace('__DATA_JSON__', json.dumps(persons, ensure_ascii=False))
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n완료: {OUT_PATH}')
    print('서버를 실행 중이라면 http://localhost:5000 을 새로고침하세요.')


if __name__ == '__main__':
    main()