"""
build_site.py
Notion CSV → 인원 디렉토리 웹페이지(index.html) 생성
"""

import csv, json, os, re, sys

CSV_PATH = os.path.join(os.path.dirname(__file__), "notion_6f3e0c2cd60182a791ce81c13b66759f_source_.csv")
OUT_PATH = os.path.join(os.path.dirname(__file__), "directory_site", "index.html")

TIMESTAMP_RE = re.compile(r'^\d{4}년 \d+월 \d+일')
DEPT_RE      = re.compile(r'.+\((\d{2}|\d{4})\)')
DATE_RE      = re.compile(r"[\'\`]?\d{2,4}[.\-\/~]")
LINKEDIN_RE  = re.compile(r'https?://(?:www\.)?linkedin\.com/in/\S+')

# 섹션 헤더 키워드 → 내부 키
SECTION_MAP = {
    '직장': 'exp', '경력': 'exp', '경험': 'exp',
    '학력': 'edu', '교육': 'edu',
    '수상': 'award', '수상경력': 'award', '수상 경력': 'award',
    '자격증': 'cert', '면허': 'cert', '자격': 'cert',
    '링크': 'link', '링크드인': 'link',
    '기타': 'etc', '관심사': 'etc', '특기': 'etc',
    '활동': 'etc', '봉사': 'etc', '프로젝트': 'etc',
}


CERT_KEYWORDS_RE = re.compile(
    r'^[\-\•\·\∙\*\※\○]?\s*('
    r'토익|토플|TOEIC|TOEFL|OPIc|오픽|JPT|JLPT|HSK|'
    r'재경관리사|투자파생상품관리인|투자자산운용사|신용분석사|자산관리사|'
    r'컴퓨터활용능력|정보처리기사|정보처리산업기사|한국사능력검정|'
    r'ADsP|ADSP|SQLD|SQLP|AWS|정보보안기사|네트워크관리사|'
    r'공인중개사|세무사|회계사|감정평가사|노무사'
    r')',
    re.IGNORECASE
)

def is_noise(text):
    t = text.strip()
    return (not t or TIMESTAMP_RE.match(t) or t in ('인원 리스트', '이름')
            or len(t) < 2)


def extract_company(text):
    """경력 텍스트에서 회사명만 추출 (날짜·괄호 제거)."""
    clean = re.sub(r'\([^)]*\)', '', text)          # 괄호 내용 제거
    clean = re.sub(r"[\'\`]?\d{2,4}[.\-\/~]\S*", '', clean)  # 날짜 제거
    clean = re.split(r'[-~·]', clean)[0]            # 구분자 앞만
    clean = clean.lstrip('•·∙*※ \t').strip()
    # 숫자 접두사 제거 (1. 2. 3.)
    clean = re.sub(r'^\d+\.\s*', '', clean).strip()
    return clean[:40] if clean else text[:40]


def parse_experiences(lines):
    """경력 라인 목록을 회사 단위로 묶어 반환."""
    entries = []
    cur_company = None
    cur_details = []

    def flush():
        if cur_company:
            detail_str = ' / '.join(cur_details) if cur_details else ''
            entries.append({
                'company': extract_company(cur_company),
                'text': cur_company + (' — ' + detail_str if detail_str else '')
            })

    for line in lines:
        if not line or len(line) < 2:
            continue
        is_detail = (line[0] in ('-', '·', '∙') or
                     (line.startswith(' ') and cur_company))
        is_numbered = bool(re.match(r'^\d+\.\s', line))
        is_bullet   = line[0] in ('•', '*', '※')

        if is_numbered or is_bullet:
            flush()
            cur_company = line.lstrip('•·∙*※0123456789. \t')
            cur_details = []
        elif is_detail and cur_company:
            cur_details.append(line.lstrip('-·∙ \t'))
        elif DATE_RE.search(line) and not cur_company:
            # 날짜가 있는 첫 줄 → 새 경력 시작
            flush()
            cur_company = line
            cur_details = []
        elif cur_company:
            # 이전 회사의 추가 정보
            if DATE_RE.search(line) or len(line) < 30:
                cur_details.append(line)
            else:
                flush()
                cur_company = line
                cur_details = []
        else:
            cur_company = line
            cur_details = []

    flush()
    return entries


def parse_person(raw):
    lines = [l.rstrip() for l in raw.split('\n')]
    non_empty = [l.strip() for l in lines if l.strip()]
    if not non_empty or is_noise(non_empty[0]):
        return None

    name = non_empty[0]
    if re.search(r'^\d', name) or 'http' in name or TIMESTAMP_RE.match(name):
        return None
    if len(name) > 20 or len(name) < 2:
        return None
    # 불릿/대시로 시작하는 줄은 이름이 아님 (예: "- 토익")
    if re.match(r'^[\-\•\·\∙\*\※\○△▶►]', name):
        return None

    # 학과·학번 + 업종 태그 (이름 다음 8줄 이내의 짧은 키워드)
    dept_lines, year = [], ''
    job_tags = []
    for line in non_empty[1:9]:
        m = DEPT_RE.match(line)
        if m:
            dept_lines.append(line)
            if not year:
                year = m.group(1)
        elif (2 <= len(line) <= 15
              and not re.search(r'[•\-\[\]①②③\(\)~/○]', line)
              and line not in ('X', 'Y', 'N', 'O')
              and not TIMESTAMP_RE.match(line)
              and re.search(r'[가-힣]', line)):
            job_tags.append(line)

    # LinkedIn
    linkedin = ''
    for line in non_empty:
        m = LINKEDIN_RE.search(line)
        if m:
            linkedin = m.group(0).rstrip(');,')
            break

    # 섹션 분류
    buckets = {'exp': [], 'edu': [], 'award': [], 'cert': [], 'link': [], 'etc': []}
    cur_bucket = 'exp'   # 기본은 경력

    for line in non_empty[len(dept_lines)+1:]:
        stripped = line.strip('[]· \t')
        # 섹션 헤더?
        if (line.startswith('[') and line.endswith(']')) or stripped in SECTION_MAP:
            key = SECTION_MAP.get(stripped, SECTION_MAP.get(line.strip('[]'), None))
            if key:
                cur_bucket = key
                continue
        if 'linkedin.com' in line or 'github.com' in line:
            continue
        buckets[cur_bucket].append(line.strip())

    # 경력 버킷에서 자격증 키워드 줄 → cert 버킷으로 이동
    exp_filtered = []
    for line in buckets['exp']:
        if CERT_KEYWORDS_RE.search(line):
            buckets['cert'].append(line)
        else:
            exp_filtered.append(line)
    buckets['exp'] = exp_filtered

    # 경력 파싱 (회사 단위로 묶기)
    experiences = parse_experiences(buckets['exp'])

    # 현재 재직 중 감지
    CURRENT_MARKERS = ('재직', '현재', '재직중', '~ )', '~)', '현재)','present','Present')
    current = ''
    is_current = False
    for exp in experiences:
        t = exp['text']
        if any(m in t for m in CURRENT_MARKERS):
            current = exp['company']
            is_current = True
            break
    if not current and experiences:
        current = experiences[0]['company']

    return {
        'name':        name,
        'dept':        ' / '.join(dept_lines),
        'year':        year,
        'job_type':    ', '.join(job_tags),
        'current':     current,
        'is_current':  is_current,
        'experiences': experiences[:10],
        'education':   [l for l in buckets['edu']  if l],
        'awards':      [l for l in buckets['award'] if l],
        'certs':       [l for l in buckets['cert']  if l],
        'etc':         [l for l in buckets['etc']   if l],
        'linkedin':    linkedin,
    }


def load_persons(csv_path):
    persons = []
    with open(csv_path, encoding='utf-8-sig') as f:
        for row in csv.reader(f):
            if not row:
                continue
            cell = row[0].strip()
            if is_noise(cell):
                continue
            p = parse_person(cell)
            if p:
                persons.append(p)
    # 이름 기준 중복 제거 (경력 정보가 더 많은 쪽 유지)
    seen = {}
    for p in persons:
        name = p['name']
        if name not in seen:
            seen[name] = p
        else:
            # 경력 수가 더 많은 쪽으로 덮어쓰기
            prev = seen[name]
            if len(p['experiences']) > len(prev['experiences']):
                seen[name] = p
    persons = list(seen.values())
    persons.sort(key=lambda x: x['name'])
    return persons


# ── HTML ──────────────────────────────────────────────────────────
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
       background: #f5f5f5; color: #111; }
header { background: #fff; border-bottom: 1px solid #e8e8e8; padding: 14px 28px;
         display: flex; align-items: center; gap: 12px; position: sticky; top: 0;
         z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.knu-logo { width: 36px; height: 36px; object-fit: contain; flex-shrink: 0; }
.header-title { display: flex; flex-direction: column; gap: 1px; }
header h1 { font-size: 1.25rem; font-weight: 900; color: #111; letter-spacing: -.03em; line-height: 1; }
.count { font-size: .72rem; color: #aaa; }
#search { margin-left: auto; padding: 8px 16px; border: 1.5px solid #ddd;
          border-radius: 20px; font-size: .88rem; width: 220px; outline: none; }
#search:focus { border-color: #111; }
.hdr-btn { padding: 8px 16px; color: #fff; border: none; border-radius: 20px;
           font-size: .83rem; font-weight: 700; cursor: pointer; transition: background .15s;
           white-space: nowrap; }
#join-btn  { background: #111; }
#join-btn:hover  { background: #333; }
#stat-btn  { background: #555; }
#stat-btn:hover  { background: #333; }
.filter-bar { padding: 10px 28px; display: flex; gap: 8px; flex-wrap: wrap; background: #fff;
              border-bottom: 1px solid #ebebeb; }
.fbtn { padding: 5px 13px; border-radius: 18px; border: 1.5px solid #ddd;
        background: #fff; font-size: .78rem; cursor: pointer; transition: all .15s; color: #555; }
.fbtn.active, .fbtn:hover { background: #111; color: #fff; border-color: #111; }
#grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px,1fr));
        gap: 14px; padding: 20px 28px 48px; }
.card { background: #fff; border-radius: 14px; padding: 18px;
        box-shadow: 0 1px 4px rgba(0,0,0,.07); transition: .2s; border: 1px solid #ebebeb; }
.card:hover { box-shadow: 0 4px 18px rgba(0,0,0,.12); transform: translateY(-2px); }
.card-top { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.avatar { width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0;
          background: linear-gradient(135deg,#333,#777);
          display: flex; align-items: center; justify-content: center;
          color: #fff; font-weight: 700; font-size: 1rem; }
.cname { font-size: .97rem; font-weight: 700; }
.dept  { font-size: .75rem; color: #999; margin-top: 1px; }
.cur-badge { display: inline-block; font-size: .78rem; color: #111; font-weight: 600;
             background: #f0f0f0; padding: 3px 9px; border-radius: 7px; margin-bottom: 8px; }
/* 경력 */
.exp-block { margin-bottom: 6px; }
.exp-company-line { display: flex; flex-wrap: wrap; align-items: center; gap: 1px; }
.exp-company { font-size: .82rem; font-weight: 600; color: #222;
               cursor: pointer; border-bottom: 1px dashed #ccc; display: inline; }
.exp-company:hover { color: #555; }
.exp-sep { font-size: .82rem; color: #bbb; }
.exp-detail { font-size: .75rem; color: #777; margin-top: 1px; }
/* 섹션 토글 */
.sec-toggle { margin-top: 8px; font-size: .75rem; color: #555; cursor: pointer;
              display: inline-block; }
.extra { display: none; margin-top: 8px; }
.extra.open { display: block; }
.sec-title { font-size: .72rem; font-weight: 700; color: #aaa; text-transform: uppercase;
             letter-spacing: .05em; margin: 7px 0 3px; }
.sec-item { font-size: .76rem; color: #555; padding: 2px 0;
            border-bottom: 1px solid #f5f5f5; }
.sec-item:last-child { border: none; }
.linkedin-link { display: inline-block; margin-top: 8px; font-size: .76rem;
                 color: #333; text-decoration: none; font-weight: 600; }
.linkedin-link:hover { text-decoration: underline; }
.card-footer { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; }
.card-edit-btn { font-size: .73rem; color: #888; background: none; border: 1px solid #e0e0e0;
                 border-radius: 7px; padding: 3px 10px; cursor: pointer; transition: all .15s; }
.card-edit-btn:hover { background: #111; color: #fff; border-color: #111; }
/* 업종 태그 선택 */
.tag-select-wrap { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 0; }
.tag-opt { padding: 4px 11px; border-radius: 16px; border: 1.5px solid #ddd;
           font-size: .76rem; cursor: pointer; transition: all .15s; color: #555;
           background: #fff; user-select: none; }
.tag-opt:hover { border-color: #999; color: #111; }
.tag-opt.selected { background: #111; color: #fff; border-color: #111; }
.no-result { grid-column: 1/-1; text-align: center; color: #bbb; padding: 60px 0; }
/* 툴팁 */
#tooltip { position: fixed; z-index: 9999; max-width: 300px; background: #fff;
           border-radius: 12px; box-shadow: 0 8px 28px rgba(0,0,0,.14);
           padding: 14px; display: none; pointer-events: none; border: 1px solid #eee; }
#tooltip.visible { display: block; animation: fi .15s ease; }
@keyframes fi { from { opacity:0; transform:translateY(4px) } to { opacity:1; transform:none } }
.tip-title { font-size: .9rem; font-weight: 700; margin-bottom: 5px; }
.tip-body  { font-size: .78rem; color: #555; line-height: 1.5; }
.tip-thumb { width: 44px; height: 44px; object-fit: contain; float: right;
             margin-left: 8px; border-radius: 6px; }
.tip-src   { font-size: .68rem; color: #ccc; margin-top: 6px; }
/* ── 공통 모달 ── */
.overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.5);
           z-index: 200; align-items: center; justify-content: center; }
.overlay.open { display: flex; }
.modal-box { background: #fff; border-radius: 18px; width: 560px; max-width: 96vw;
             max-height: 90vh; overflow-y: auto; padding: 28px 30px 24px;
             box-shadow: 0 12px 48px rgba(0,0,0,.22); position: relative; }
.modal-box h2 { font-size: 1.1rem; font-weight: 800; color: #111; margin-bottom: 20px; }
.modal-close { position: absolute; top: 18px; right: 20px; background: none; border: none;
               font-size: 1.3rem; cursor: pointer; color: #999; line-height: 1; }
.modal-close:hover { color: #111; }
/* LinkedIn 로그인 단계 */
#login-step { margin-bottom: 16px; padding: 14px 16px; background: #f8f8f8;
              border: 1.5px solid #ddd; border-radius: 12px; }
#login-step.hidden { display: none; }
.login-step-title { font-size: .82rem; font-weight: 700; color: #333; margin-bottom: 6px; }
.login-step-desc { font-size: .78rem; color: #888; margin-bottom: 10px; line-height: 1.5; }
#li-login-btn { padding: 8px 18px; background: #111; color: #fff; border: none;
                border-radius: 10px; font-size: .83rem; font-weight: 600; cursor: pointer; }
#li-login-btn:hover { background: #333; }
#li-login-btn:disabled { background: #999; cursor: default; }
#login-poll-msg { font-size: .78rem; color: #888; margin-top: 8px; min-height: 18px; }
/* LinkedIn URL step */
#li-step { margin-bottom: 20px; padding-bottom: 18px; border-bottom: 1px solid #eee; }
#li-step label { font-size: .8rem; font-weight: 600; color: #555; display: block; margin-bottom: 6px; }
.li-row { display: flex; gap: 8px; }
.li-row input { flex: 1; padding: 8px 12px; border: 1.5px solid #ddd; border-radius: 10px;
                font-size: .85rem; outline: none; }
.li-row input:focus { border-color: #111; }
.li-fetch-btn { padding: 8px 14px; background: #111; color: #fff; border: none;
                border-radius: 10px; font-size: .82rem; font-weight: 600; cursor: pointer;
                white-space: nowrap; }
.li-fetch-btn:hover { background: #333; }
.li-fetch-btn:disabled { background: #999; cursor: default; }
#li-status { font-size: .78rem; margin-top: 6px; min-height: 18px; color: #888; }
/* 폼 필드 */
.form-field { margin-bottom: 14px; }
.form-field label { font-size: .8rem; font-weight: 600; color: #555; display: block; margin-bottom: 5px; }
.form-field input[type=text] { width: 100%; padding: 8px 12px; border: 1.5px solid #ddd;
                               border-radius: 10px; font-size: .85rem; outline: none; }
.form-field input:focus { border-color: #111; }
/* 동적 행 섹션 */
.dyn-section { margin-bottom: 16px; }
.dyn-title { font-size: .82rem; font-weight: 700; color: #333; margin-bottom: 8px; }
.dyn-row { display: grid; gap: 6px; margin-bottom: 8px; padding: 10px 12px;
           background: #f8f8f8; border-radius: 10px; position: relative; }
.dyn-row input { padding: 6px 10px; border: 1.5px solid #ddd; border-radius: 8px;
                 font-size: .82rem; outline: none; background: #fff; }
.dyn-row input:focus { border-color: #111; }
.dyn-row input::placeholder { color: #ccc; }
.dyn-del { position: absolute; top: 8px; right: 10px; background: none; border: none;
           color: #ccc; font-size: 1.1rem; cursor: pointer; line-height: 1; padding: 0; }
.dyn-del:hover { color: #e55; }
.dyn-add { font-size: .78rem; color: #555; background: none; border: 1.5px dashed #ccc;
           border-radius: 8px; padding: 6px 14px; cursor: pointer; width: 100%; }
.dyn-add:hover { background: #f0f0f0; }
/* 제출 버튼 */
#modal-submit { width: 100%; padding: 12px; background: #111; color: #fff; border: none;
                border-radius: 12px; font-size: .95rem; font-weight: 700; cursor: pointer;
                margin-top: 8px; transition: background .15s; }
#modal-submit:hover { background: #333; }
#modal-submit:disabled { background: #999; cursor: default; }
#form-msg { text-align: center; font-size: .82rem; margin-top: 10px; min-height: 20px; }
.member-badge { display: inline-block; font-size: .68rem; background: #f0f0f0; color: #555;
                border-radius: 5px; padding: 1px 6px; margin-left: 6px; vertical-align: middle; }
.cur-emp-badge { display: inline-block; font-size: .67rem; background: #111; color: #fff;
                 border-radius: 4px; padding: 1px 6px; margin-left: 5px; vertical-align: middle; }
.job-tag { font-size: .73rem; color: #555; background: #f0f0f0; display: inline-block;
           padding: 2px 8px; border-radius: 6px; margin-bottom: 7px; }
.hidden { display: none !important; }
/* ── 회사명 자동완성 ── */
.ac-wrap { position: relative; }
.ac-list { position: absolute; top: calc(100% + 4px); left: 0; right: 0; background: #fff;
           border: 1.5px solid #ddd; border-radius: 10px;
           box-shadow: 0 6px 20px rgba(0,0,0,.1); z-index: 500;
           max-height: 200px; overflow-y: auto; display: none; }
.ac-list.open { display: block; }
.ac-item { padding: 7px 12px; font-size: .82rem; cursor: pointer;
           display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #f5f5f5; }
.ac-item:last-child { border: none; }
.ac-item:hover, .ac-item.focused { background: #f5f5f5; }
/* ── 통계 모달 ── */
#stat-modal { width: 620px; }
.stat-section { margin-bottom: 24px; }
.stat-section h3 { font-size: .85rem; font-weight: 700; color: #111; margin-bottom: 12px;
                   padding-bottom: 6px; border-bottom: 2px solid #111; }
.stat-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.stat-label { font-size: .78rem; color: #333; width: 120px; flex-shrink: 0;
              white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stat-bar-wrap { flex: 1; background: #f0f0f0; border-radius: 4px; height: 18px; overflow: hidden; }
.stat-bar { height: 100%; background: #111; border-radius: 4px;
            transition: width .6s ease; display: flex; align-items: center;
            justify-content: flex-end; padding-right: 6px; }
.stat-bar span { font-size: .65rem; color: #fff; font-weight: 700; white-space: nowrap; }
.stat-val { font-size: .78rem; color: #555; width: 36px; text-align: right; flex-shrink: 0; }
.stat-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 24px; }
.stat-card { background: #f8f8f8; border-radius: 12px; padding: 16px; text-align: center; }
.stat-card .big { font-size: 2rem; font-weight: 800; color: #111; }
.stat-card .label { font-size: .78rem; color: #777; margin-top: 4px; }
.donut-wrap { display: flex; align-items: center; gap: 20px; }
.donut-legend { display: flex; flex-direction: column; gap: 8px; }
.legend-item { display: flex; align-items: center; gap: 8px; font-size: .8rem; }
.legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
"""

JS = r"""
const CSV_DATA = __DATA_JSON__;
let ALL_DATA = [...CSV_DATA];

const JOB_TAGS = [
  '기획','정책','광고','마케팅','금융','공기업(공공기관)','데이터','부동산',
  'IT','국내정치','국가안보','국제기구','농업','언론','전략','컨설팅',
  'ESG','개발','경영지원','인사','총무','물류','무역','교육','통계',
  '관광','보험','자산운용업','철강','바이오','과학산업','반도체','증권사',
  'PF','배터리','자동차','부품','타이어','사업개발','인플루언서','게임',
  '투자','심사','기후','제조업','보안','생산기술','품질','방위산업',
  'MD','생산관리','설계','로봇','차량제어','SW개발','미들웨어','영상','ROS',
];
const JOB_TAG_SET = new Set(JOB_TAGS);

// ── Supabase 설정 ────────────────────────────────────────────────
const SB_URL = 'https://vkrbdqzwvflrmgwelmfo.supabase.co';
const SB_KEY = 'sb_publishable_J7WpyPZp2ttSFQA1_ZZB4g_mViK52fQ';
const SB_HDR = { 'apikey': SB_KEY, 'Authorization': 'Bearer ' + SB_KEY,
                 'Content-Type': 'application/json', 'Prefer': 'return=minimal' };

async function sbGet(){
  const r = await fetch(SB_URL+'/rest/v1/members?select=*&order=created_at.asc', {headers: SB_HDR});
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}
async function sbInsertOrUpdate(data){
  // name 기준 upsert
  const r = await fetch(SB_URL+'/rest/v1/members?on_conflict=name', {
    method: 'POST',
    headers: { ...SB_HDR, 'Prefer': 'resolution=merge-duplicates,return=minimal' },
    body: JSON.stringify(data),
  });
  if(!r.ok) throw new Error(await r.text());
}

function av(n){ return (n||'?')[0]; }


function renderCard(p){
  const memberBadge  = p._member    ? '<span class="member-badge">자기소개</span>' : '';
  const curBadge     = p.is_current ? ' <span class="cur-emp-badge">현직</span>' : '';
  const jobTag       = p.job_type   ? `<div class="job-tag">${p.job_type}</div>` : '';

  const expHtml = (p.experiences||[]).map(e => {
    const detail = e.text && e.text !== e.company
      ? e.text.replace(e.company,'').replace(/^[\s\·\-—]+/,'') : '';
    const parts = (e.company||'').split(/\s*[,，]\s*/).map(s=>s.trim()).filter(Boolean);
    const compHtml = parts.map(pt=>
      `<span class="exp-company" data-q="${encodeURIComponent(pt)}">${pt}</span>`
    ).join('<span class="exp-sep">, </span>');
    return `<div class="exp-block">
       <div class="exp-company-line">${compHtml}</div>
       ${detail ? `<div class="exp-detail">${detail}</div>` : ''}
     </div>`;
  }).join('');

  const sections = [
    {key:'education', label:'학력'},
    {key:'awards',    label:'활동/수상'},
    {key:'certs',     label:'자격증'},
    {key:'etc',       label:'기타'},
  ];
  const extraHtml = sections.map(s => {
    const items = p[s.key]||[];
    if(!items.length) return '';
    return `<div class="sec-title">${s.label}</div>`
      + items.map(i=>`<div class="sec-item">${i}</div>`).join('');
  }).join('');

  const hasExtra = sections.some(s=>(p[s.key]||[]).length>0);
  const toggle = hasExtra
    ? `<span class="sec-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.textContent=this.textContent==='▼ 더 보기'?'▲ 접기':'▼ 더 보기'">▼ 더 보기</span>
       <div class="extra">${extraHtml}</div>` : '';

  const badge  = p.current ? `<div class="cur-badge">🏢 ${p.current}</div>` : '';
  const lilink = p.linkedin ? `<a class="linkedin-link" href="${p.linkedin}" target="_blank">LinkedIn →</a>` : '';
  const safeN  = p.name.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  const editBtn = `<button class="card-edit-btn" onclick="openEditModal('${safeN}')">✏ 수정</button>`;

  return `<div class="card">
    <div class="card-top">
      <div class="avatar">${av(p.name)}</div>
      <div><div class="cname">${p.name}${memberBadge}${curBadge}</div><div class="dept">${p.dept||''}</div></div>
    </div>
    ${jobTag}${badge}${expHtml}${toggle}
    <div class="card-footer">${lilink}${editBtn}</div>
  </div>`;
}

function render(list){
  const g = document.getElementById('grid');
  g.innerHTML = list.length
    ? list.map(renderCard).join('')
    : '<div class="no-result">검색 결과 없음</div>';
  document.getElementById('cnt').textContent = `(${list.length}명)`;
}

function buildFilters(){
  const bar = document.getElementById('fbar');
  bar.querySelectorAll('.fbtn:not([data-filter=""])').forEach(b=>b.remove());

  // 현직 버튼
  const curBtn = document.createElement('button');
  curBtn.className='fbtn'; curBtn.dataset.filter='__current__';
  curBtn.textContent='현직';
  bar.appendChild(curBtn);

  // 업종 태그 수집 (공식 목록만, 빈도순)
  const jobCount = {};
  ALL_DATA.forEach(p=>{
    (p.job_type||'').split(/\s*,\s*/).filter(t=>JOB_TAG_SET.has(t)).forEach(t=>{
      jobCount[t] = (jobCount[t]||0) + 1;
    });
  });
  Object.entries(jobCount).sort((a,b)=>b[1]-a[1]).forEach(([tag])=>{
    const b = document.createElement('button');
    b.className='fbtn'; b.dataset.filter='__job__'+tag;
    b.textContent=tag;
    bar.appendChild(b);
  });

  bar.querySelectorAll('.fbtn').forEach(b=>b.addEventListener('click',()=>{
    bar.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); applyFilter();
  }));
}

function applyFilter(){
  const q = document.getElementById('search').value.toLowerCase();
  const f = document.querySelector('.fbtn.active')?.dataset.filter||'';
  render(ALL_DATA.filter(p=>{
    if(f==='__current__' && !p.is_current) return false;
    if(f.startsWith('__job__')){
      const tag = f.slice(7);
      const tags = (p.job_type||'').split(/\s*,\s*/);
      if(!tags.includes(tag)) return false;
    }
    if(!q) return true;
    const blob = [p.name,p.dept||'',p.job_type||'',(p.experiences||[]).map(e=>e.text).join(' '),
                  p.current||'',(p.education||[]).join(' '),(p.awards||[]).join(' '),
                  (p.certs||[]).join(' '),(p.etc||[]).join(' ')].join(' ').toLowerCase();
    return blob.includes(q);
  }));
}
document.getElementById('search').addEventListener('input', applyFilter);

// ── 회원 API 로드 & 머지 ─────────────────────────────────────────
function memberToCard(m){
  const exps = (m.experiences||[]).map(e=>({
    company: e.company||'',
    text: [e.company, e.role, e.period].filter(Boolean).join(' · ')
  })).filter(e=>e.company);
  const current = exps[0]?.company || '';
  const edLines = (m.education||[]).map(e=>[e.school,e.major,e.period].filter(Boolean).join(' / '));
  const certLines = (m.certs||[]).map(c=>[c.name,c.issuer,c.date].filter(Boolean).join(' · '));
  const etcLines = (m.activities||[]).map(a=>[a.name,a.role,a.period].filter(Boolean).join(' · '));
  return {
    name: m.name||'',
    dept: m.dept||'',
    year: m.year||'',
    job_type: m.job_type||'',
    current,
    is_current: m.is_current||false,
    experiences: exps,
    education: edLines,
    awards: [],
    certs: certLines,
    etc: etcLines,
    linkedin: m.linkedin||'',
    _member: true,
  };
}

async function loadMembers(){
  try{
    const members = await sbGet();
    if(!members.length) return;
    const cards = members.map(memberToCard);
    // Supabase 데이터가 CSV보다 우선 (수정된 정보 반영)
    const sbNames = new Set(cards.map(c=>c.name));
    const csvOnly = CSV_DATA.filter(p=>!sbNames.has(p.name));
    ALL_DATA = [...csvOnly, ...cards];
    buildFilters();
    applyFilter();
  }catch(e){ /* Supabase 연결 실패 시 무시 */ }
}

function openEditModal(name){
  const p = ALL_DATA.find(x=>x.name===name);
  if(!p) return;
  overlay.classList.add('open');
  document.getElementById('li-status').textContent='';
  document.getElementById('login-poll-msg').textContent='';
  document.getElementById('form-msg').textContent='';

  // 기본 정보
  document.getElementById('f-name').value = p.name||'';
  document.getElementById('li-url').value  = p.linkedin||'';

  // 업종 태그 프리셀렉트
  const existingTags = new Set((p.job_type||'').split(/\s*,\s*/).filter(Boolean));
  document.querySelectorAll('.tag-opt').forEach(el=>{
    el.classList.toggle('selected', existingTags.has(el.dataset.tag));
  });

  // 경력
  clearSection('exp-rows');
  (p.experiences||[]).forEach(e=>{
    const role = (e.text||'').replace(e.company||'','').replace(/^[\s·\-—]+/,'').trim();
    addRow('exp-rows', {company: e.company||'', role, period:''});
  });
  if(!(p.experiences||[]).length) addRow('exp-rows',{});

  // 학력
  clearSection('edu-rows');
  (p.education||[]).forEach(e=>{
    addRow('edu-rows', {school: typeof e==='string'?e:(e.school||'')});
  });
  if(!(p.education||[]).length) addRow('edu-rows',{});

  // 활동
  clearSection('act-rows');
  const acts = p.activities||p.etc||[];
  acts.forEach(a=>{ addRow('act-rows', {name: typeof a==='string'?a:(a.name||'')}); });
  if(!acts.length) addRow('act-rows',{});

  // 자격증
  clearSection('cert-rows');
  (p.certs||[]).forEach(c=>{
    addRow('cert-rows', {name: typeof c==='string'?c:(c.name||'')});
  });
  if(!(p.certs||[]).length) addRow('cert-rows',{});

  checkSessionStatus();
}

const tip = document.getElementById('tooltip');
let ht = null;

function cleanQuery(raw){
  return decodeURIComponent(raw)
    .replace(/주식회사|유한회사|\(주\)|\(유\)|㈜|㈔|\(재\)|\(사\)/g,'')
    .replace(/\([^)]*\)/g,'')
    .replace(/[\d]{2,4}[.\-\/~]\S*/g,'')
    .replace(/\d+기\b/g,'')
    .replace(/수료|졸업|인턴십?|계약직|정규직|파견|아르바이트|사원|주임|대리|과장|팀장|부장/g,'')
    .replace(/[`'~_]/g,'')
    .replace(/\s{2,}/g,' ')
    .trim();
}

async function searchWiki(base, query){
  try{
    const r=await fetch(base+'/api/rest_v1/page/summary/'+encodeURIComponent(query));
    if(r.ok){const j=await r.json();if(j.type!=='disambiguation'&&j.extract)return j;}
  }catch(e){}
  try{
    const sr=await fetch(base+'/w/api.php?action=opensearch&search='+encodeURIComponent(query)+'&limit=1&format=json&origin=*');
    if(sr.ok){
      const [,titles]=await sr.json();
      if(titles&&titles[0]){
        const pr=await fetch(base+'/api/rest_v1/page/summary/'+encodeURIComponent(titles[0]));
        if(pr.ok){const j=await pr.json();if(j.extract)return j;}
      }
    }
  }catch(e){}
  return null;
}

async function fetchWiki(rawQ){
  const full = cleanQuery(rawQ);
  if(!full) return null;
  const words = full.split(/\s+/).filter(w=>w.length>1);
  const candidates = [full];
  if(words.length>1) candidates.push(words[0]);
  if(words.length>2) candidates.push(words.slice(0,2).join(' '));
  for(const base of ['https://ko.wikipedia.org','https://en.wikipedia.org']){
    for(const q of candidates){
      const result = await searchWiki(base, q);
      if(result) return result;
    }
  }
  return null;
}

function positionTip(target){
  const rect=target.getBoundingClientRect();
  let top=rect.bottom+6, left=rect.left;
  if(left+310>window.innerWidth) left=window.innerWidth-316;
  if(top+200>window.innerHeight) top=rect.top-210;
  tip.style.top=top+'px'; tip.style.left=left+'px';
}

function showTip(target,q){
  clearTimeout(ht);
  tip.innerHTML='<div class="tip-body" style="color:#bbb">검색 중…</div>';
  tip.classList.add('visible');
  positionTip(target);
  fetchWiki(q).then(d=>{
    if(!tip.classList.contains('visible'))return;
    if(!d){tip.innerHTML='<div class="tip-body" style="color:#bbb">정보 없음</div>';return;}
    const th=d.thumbnail?.source?`<img class="tip-thumb" src="${d.thumbnail.source}" alt="">`:' ';
    tip.innerHTML=th+`<div class="tip-title">${d.title}</div>`
      +`<div class="tip-body">${(d.extract||'').slice(0,220)}…</div>`
      +'<div class="tip-src">출처: 위키피디아</div>';
    positionTip(target);
  });
}
function hideTip(){ht=setTimeout(()=>tip.classList.remove('visible'),200);}

function attachTags(){
  const grid=document.getElementById('grid');
  grid.addEventListener('mouseover',e=>{
    const tag=e.target.closest('.exp-company');
    if(tag){clearTimeout(ht);showTip(tag,tag.dataset.q);}
  });
  grid.addEventListener('mouseout',e=>{
    if(e.target.closest('.exp-company'))hideTip();
  });
}

// ── 회원가입 모달 ────────────────────────────────────────────────
const overlay = document.getElementById('modal-overlay');

document.getElementById('join-btn').addEventListener('click', async ()=>{
  overlay.classList.add('open');
  document.getElementById('li-status').textContent='';
  document.getElementById('login-poll-msg').textContent='';
  await checkSessionStatus();
});
document.querySelector('#modal-overlay .modal-close').addEventListener('click', closeModal);
overlay.addEventListener('click', e=>{ if(e.target===overlay) closeModal(); });
function closeModal(){
  overlay.classList.remove('open');
  document.getElementById('form-msg').textContent='';
  clearInterval(_loginPollTimer);
}

// 세션 상태 확인 → 로그인 버튼 텍스트 업데이트
async function checkSessionStatus(){
  try{
    const r = await fetch('/api/session-status');
    const j = await r.json();
    if(j.exists){
      document.getElementById('login-desc').textContent='이미 로그인되어 있습니다. 아래에서 URL을 입력해 자동 불러오기를 사용하세요.';
      document.getElementById('li-login-btn').textContent='다시 로그인';
    }
  }catch(e){}
}

// LinkedIn 로그인 버튼
let _loginPollTimer = null;
document.getElementById('li-login-btn').addEventListener('click', async()=>{
  const btn = document.getElementById('li-login-btn');
  btn.disabled=true; btn.textContent='브라우저 여는 중…';
  document.getElementById('login-poll-msg').textContent='';
  try{
    await fetch('/api/login', {method:'POST'});
  }catch(e){
    document.getElementById('login-poll-msg').textContent='서버 연결 실패';
    btn.disabled=false; btn.textContent='LinkedIn 로그인하기';
    return;
  }
  document.getElementById('login-poll-msg').textContent='브라우저가 열렸습니다. LinkedIn에 로그인해주세요…';
  // 2초마다 상태 폴링
  _loginPollTimer = setInterval(async()=>{
    try{
      const r = await fetch('/api/login/status');
      const j = await r.json();
      document.getElementById('login-poll-msg').textContent = j.msg||'';
      if(j.state==='done'){
        clearInterval(_loginPollTimer);
        document.getElementById('login-desc').textContent='로그인 완료! 아래 URL을 입력해 자동 불러오기를 사용하세요.';
        document.getElementById('login-poll-msg').textContent='';
        btn.disabled=false; btn.textContent='다시 로그인';
      } else if(j.state==='error'||j.state==='timeout'){
        clearInterval(_loginPollTimer);
        btn.disabled=false; btn.textContent='다시 시도';
      }
    }catch(e){}
  }, 2000);
});

// LinkedIn 자동 불러오기
document.getElementById('li-fetch-btn').addEventListener('click', async()=>{
  const url = document.getElementById('li-url').value.trim();
  if(!url){ document.getElementById('li-status').textContent='URL을 입력하세요'; return; }
  const btn = document.getElementById('li-fetch-btn');
  btn.disabled=true; btn.textContent='불러오는 중…';
  document.getElementById('li-status').textContent='LinkedIn 스크래핑 중 (브라우저가 열립니다)…';
  try{
    const r = await fetch('/api/scrape?url='+encodeURIComponent(url));
    const d = await r.json();
    if(d.error){ document.getElementById('li-status').textContent='오류: '+d.error; return; }
    prefillForm(d);
    document.getElementById('li-status').textContent='자동 완성됨. 수정 후 제출하세요.';
  }catch(e){
    document.getElementById('li-status').textContent='서버 연결 실패. 수동 입력해 주세요.';
  }finally{
    btn.disabled=false; btn.textContent='자동 불러오기';
  }
});

function prefillForm(d){
  if(d.name) document.getElementById('f-name').value = d.name;
  // 경력 파싱 (pipe 구분)
  if(d.experience){
    const exps = d.experience.split(' | ').map(s=>s.trim()).filter(Boolean);
    clearSection('exp-rows');
    exps.forEach(e=>addRow('exp-rows', {company: e}));
    if(!exps.length) addRow('exp-rows',{});
  }
  // 학력
  if(d.education){
    const edus = d.education.split(' | ').map(s=>s.trim()).filter(Boolean);
    clearSection('edu-rows');
    edus.forEach(e=>addRow('edu-rows',{school:e}));
    if(!edus.length) addRow('edu-rows',{});
  }
  // 자격증
  if(d.certs){
    const certs = d.certs.split(' | ').map(s=>s.trim()).filter(Boolean);
    clearSection('cert-rows');
    certs.forEach(c=>addRow('cert-rows',{name:c}));
    if(!certs.length) addRow('cert-rows',{});
  }
}

// ── 회사명 자동완성 ─────────────────────────────────────────────
function getLocalCompanies(q){
  const set = new Set();
  ALL_DATA.forEach(p=>(p.experiences||[]).forEach(e=>{
    if(e.company && e.company.toLowerCase().includes(q.toLowerCase())) set.add(e.company);
  }));
  return [...set].slice(0, 6);
}

function attachCompanyAutocomplete(input){
  const wrap = document.createElement('div');
  wrap.className = 'ac-wrap';
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);

  const list = document.createElement('div');
  list.className = 'ac-list';
  wrap.appendChild(list);

  let _debounce = null;
  let _focused = -1;
  let _items = [];

  function renderList(locals){
    _items = [];
    list.innerHTML = '';
    locals.forEach(name=>{
      _items.push(name);
      const el = document.createElement('div');
      el.className = 'ac-item';
      el.innerHTML = `<span>${name}</span>`;
      el.addEventListener('mousedown', e=>{ e.preventDefault(); input.value=name; hideList(); });
      list.appendChild(el);
    });
    _focused = -1;
    if(_items.length) list.classList.add('open'); else list.classList.remove('open');
  }

  function hideList(){ list.classList.remove('open'); _focused=-1; }

  function updateFocus(idx){
    const els = list.querySelectorAll('.ac-item');
    els.forEach(e=>e.classList.remove('focused'));
    if(idx>=0 && idx<els.length){ els[idx].classList.add('focused'); _focused=idx; }
  }

  input.addEventListener('input', ()=>{
    const q = input.value.trim();
    if(q.length < 1){ hideList(); return; }
    renderList(getLocalCompanies(q));
  });

  input.addEventListener('keydown', e=>{
    if(!list.classList.contains('open')) return;
    if(e.key==='ArrowDown'){ e.preventDefault(); updateFocus(Math.min(_focused+1,_items.length-1)); }
    else if(e.key==='ArrowUp'){ e.preventDefault(); updateFocus(Math.max(_focused-1,0)); }
    else if(e.key==='Enter' && _focused>=0){ e.preventDefault(); input.value=_items[_focused]; hideList(); }
    else if(e.key==='Escape'){ hideList(); }
  });

  input.addEventListener('blur', ()=>setTimeout(hideList, 150));
}

// 동적 행 헬퍼
function clearSection(id){ document.getElementById(id).innerHTML=''; }

function addRow(sectionId, vals={}){
  const section = document.getElementById(sectionId);
  const row = document.createElement('div');
  row.className='dyn-row';

  const configs = {
    'exp-rows': [
      {name:'company', placeholder:'회사명'},
      {name:'role',    placeholder:'직책 / 포지션'},
      {name:'period',  placeholder:'기간 (예: 2022.03 ~ 현재)', wide:true},
    ],
    'edu-rows': [
      {name:'school',  placeholder:'학교명'},
      {name:'major',   placeholder:'전공'},
      {name:'period',  placeholder:'기간 (예: 2018 ~ 2022)', wide:true},
    ],
    'act-rows': [
      {name:'name',    placeholder:'동아리 / 활동명'},
      {name:'role',    placeholder:'역할'},
      {name:'period',  placeholder:'기간', wide:true},
    ],
    'cert-rows': [
      {name:'name',    placeholder:'자격증명'},
      {name:'issuer',  placeholder:'발급기관'},
      {name:'date',    placeholder:'취득일 (예: 2023.05)', wide:true},
    ],
  };

  const fields = configs[sectionId]||[];
  let html = '';
  fields.forEach(f=>{
    const val = (vals[f.name]||'').replace(/"/g,'&quot;');
    if(f.wide){
      html += `<input type="text" name="${f.name}" placeholder="${f.placeholder}" value="${val}">`;
    } else {
      html += `<input type="text" name="${f.name}" placeholder="${f.placeholder}" value="${val}">`;
    }
  });
  html += '<button type="button" class="dyn-del" title="삭제">✕</button>';
  row.innerHTML = html;
  row.querySelector('.dyn-del').addEventListener('click',()=>row.remove());
  section.appendChild(row);
  const compInput = row.querySelector('input[name="company"]');
  if(compInput) attachCompanyAutocomplete(compInput);
}

// 각 섹션 + 버튼 초기화
['exp','edu','act','cert'].forEach(key=>{
  const sId = key+'-rows';
  addRow(sId, {});
  document.getElementById('add-'+key).addEventListener('click',()=>addRow(sId,{}));
});

// 폼 제출
document.getElementById('modal-submit').addEventListener('click', async()=>{
  const name = document.getElementById('f-name').value.trim();
  if(!name){ document.getElementById('form-msg').textContent='이름은 필수입니다'; return; }

  function collectRows(sectionId, fields){
    return Array.from(document.getElementById(sectionId).querySelectorAll('.dyn-row'))
      .map(row=>{
        const obj={};
        fields.forEach(f=>{
          const inp = row.querySelector(`input[name="${f}"]`);
          obj[f] = inp ? inp.value.trim() : '';
        });
        return obj;
      }).filter(obj=>Object.values(obj).some(v=>v));
  }

  const selectedTags = [...document.querySelectorAll('.tag-opt.selected')].map(el=>el.dataset.tag);
  const payload = {
    name,
    linkedin:    document.getElementById('li-url').value.trim(),
    job_type:    selectedTags.join(', '),
    experiences: collectRows('exp-rows',['company','role','period']),
    education:   collectRows('edu-rows',['school','major','period']),
    activities:  collectRows('act-rows',['name','role','period']),
    certs:       collectRows('cert-rows',['name','issuer','date']),
  };

  const btn = document.getElementById('modal-submit');
  btn.disabled=true; btn.textContent='저장 중…';
  try{
    await sbInsertOrUpdate(payload);
    document.getElementById('form-msg').style.color='#5b5ef4';
    document.getElementById('form-msg').textContent='저장되었습니다! 명단에 추가됩니다.';
    await loadMembers();
    setTimeout(closeModal, 1600);
  }catch(e){
    document.getElementById('form-msg').style.color='#e55';
    document.getElementById('form-msg').textContent=friendlyError(e.message);
  }finally{
    btn.disabled=false; btn.textContent='제출하기';
  }
});

// ── 한국어 오류 메시지 ────────────────────────────────────────────
function friendlyError(msg){
  if(!msg) return '오류가 발생했습니다.';
  if(msg.includes('unique')||msg.includes('duplicate')||msg.includes('already exists')) return '이미 등록된 이름입니다.';
  if(msg.includes('not-null')||msg.includes('null value')||msg.includes('violates')) return '필수 항목을 입력해주세요.';
  if(msg.includes('network')||msg.includes('fetch')||msg.includes('Failed')) return '네트워크 오류. 인터넷 연결을 확인해주세요.';
  if(msg.includes('timeout')) return '요청 시간이 초과됐습니다. 다시 시도해주세요.';
  return '오류가 발생했습니다. 다시 시도해주세요.';
}

// ── 통계 모달 ─────────────────────────────────────────────────────
document.getElementById('stat-btn').addEventListener('click', ()=>{
  document.getElementById('stat-overlay').classList.add('open');
  renderStats();
});
document.getElementById('stat-close').addEventListener('click', ()=>{
  document.getElementById('stat-overlay').classList.remove('open');
});
document.getElementById('stat-overlay').addEventListener('click', e=>{
  if(e.target===document.getElementById('stat-overlay'))
    document.getElementById('stat-overlay').classList.remove('open');
});

function renderStats(){
  const data = ALL_DATA;
  const total = data.length;
  const currentCount = data.filter(p=>p.is_current).length;

  // 요약 카드
  document.getElementById('st-total').textContent   = total;
  document.getElementById('st-current').textContent = currentCount;
  document.getElementById('st-pct').textContent     = total ? Math.round(currentCount/total*100)+'%' : '0%';

  // 학번 분포
  const yearMap = {};
  data.forEach(p=>{ if(p.year){ const y='20'+p.year; yearMap[y]=(yearMap[y]||0)+1; } });
  renderBars('year-bars', yearMap, total, '학번');

  // 업종 분포 (공식 태그만, multi-select 합산)
  const jobMap = {};
  data.forEach(p=>{
    (p.job_type||'').split(/\s*,\s*/).filter(t=>JOB_TAG_SET.has(t)).forEach(t=>{
      jobMap[t] = (jobMap[t]||0) + 1;
    });
  });
  renderBars('job-bars', jobMap, total);

  // 현직/졸업 도넛
  renderDonut(currentCount, total - currentCount);
}

function renderBars(elId, map, total, suffix=''){
  const el = document.getElementById(elId);
  const sorted = Object.entries(map).sort((a,b)=>b[1]-a[1]);
  const max = sorted[0]?.[1]||1;
  el.innerHTML = sorted.map(([k,v])=>{
    const pct = Math.round(v/max*100);
    return `<div class="stat-row">
      <div class="stat-label">${k}${suffix}</div>
      <div class="stat-bar-wrap">
        <div class="stat-bar" style="width:${pct}%"><span>${v}명</span></div>
      </div>
      <div class="stat-val">${Math.round(v/total*100)}%</div>
    </div>`;
  }).join('');
}

function renderDonut(current, alumni){
  const total = current + alumni;
  const pct = total ? Math.round(current/total*100) : 0;
  const r = 54, cx = 64, cy = 64;
  const circ = 2*Math.PI*r;
  const dash = circ * pct / 100;
  document.getElementById('donut-svg').innerHTML = `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#eee" stroke-width="16"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#111" stroke-width="16"
      stroke-dasharray="${dash} ${circ}" stroke-dashoffset="${circ*0.25}"
      stroke-linecap="round" transform="rotate(-90 ${cx} ${cy})"/>
    <text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="middle"
      font-size="18" font-weight="800" fill="#111">${pct}%</text>`;
  document.getElementById('donut-legend').innerHTML = `
    <div class="legend-item"><div class="legend-dot" style="background:#111"></div>현직 ${current}명</div>
    <div class="legend-item"><div class="legend-dot" style="background:#eee;border:1px solid #ccc"></div>동문 ${alumni}명</div>`;
}

// 업종 태그 선택 UI 초기화
(function initTagSelect(){
  const wrap = document.getElementById('job-tag-select');
  JOB_TAGS.forEach(tag=>{
    const el = document.createElement('span');
    el.className='tag-opt'; el.dataset.tag=tag; el.textContent=tag;
    el.addEventListener('click', ()=>el.classList.toggle('selected'));
    wrap.appendChild(el);
  });
})();

attachTags(); buildFilters(); render(ALL_DATA); loadMembers();
"""

MODAL_HTML = """
<!-- 통계 모달 -->
<div id="stat-overlay" class="overlay">
<div id="stat-modal" class="modal-box">
  <button id="stat-close" class="modal-close" title="닫기">✕</button>
  <h2>인원 통계</h2>
  <div class="stat-cards">
    <div class="stat-card"><div class="big" id="st-total">-</div><div class="label">전체 인원</div></div>
    <div class="stat-card"><div class="big" id="st-current">-</div><div class="label">현직자</div></div>
  </div>
  <div class="stat-section">
    <h3>현직자 비율</h3>
    <div class="donut-wrap">
      <svg id="donut-svg" width="128" height="128" viewBox="0 0 128 128"></svg>
      <div id="donut-legend" class="donut-legend"></div>
      <div style="margin-left:auto;font-size:2rem;font-weight:800;color:#111" id="st-pct">-</div>
    </div>
  </div>
  <div class="stat-section">
    <h3>학번별 분포</h3>
    <div id="year-bars"></div>
  </div>
  <div class="stat-section">
    <h3>업종별 분포</h3>
    <div id="job-bars"></div>
  </div>
</div>
</div>

<!-- 회원가입 모달 -->
<div id="modal-overlay" class="overlay">
<div id="modal" class="modal-box">
  <button class="modal-close" title="닫기">✕</button>
  <h2>회원 정보 등록</h2>

  <!-- 1단계: LinkedIn 로그인 -->
  <div id="login-step">
    <div class="login-step-title">1단계 — LinkedIn 로그인</div>
    <div class="login-step-desc" id="login-desc">로그인하면 프로필 정보를 자동으로 불러올 수 있어요.<br>로그인 완료 후 브라우저가 자동으로 닫힙니다.</div>
    <button id="li-login-btn">LinkedIn 로그인하기</button>
    <div id="login-poll-msg"></div>
  </div>

  <!-- 2단계: LinkedIn URL 입력 -->
  <div id="li-step">
    <label>2단계 — LinkedIn 프로필 URL 입력 (선택)</label>
    <div class="li-row">
      <input id="li-url" type="text" placeholder="https://www.linkedin.com/in/username">
      <button id="li-fetch-btn" class="li-fetch-btn">자동 불러오기</button>
    </div>
    <div id="li-status"></div>
  </div>

  <div id="form-body">
    <!-- 기본 정보 -->
    <div class="form-field">
      <label>이름 *</label>
      <input id="f-name" type="text" placeholder="홍길동">
    </div>

    <!-- 직장 -->
    <div class="dyn-section">
      <div class="dyn-title">직장 경력</div>
      <div id="exp-rows"></div>
      <button id="add-exp" class="dyn-add">+ 직장 추가</button>
    </div>

    <!-- 학력 -->
    <div class="dyn-section">
      <div class="dyn-title">학력</div>
      <div id="edu-rows"></div>
      <button id="add-edu" class="dyn-add">+ 학력 추가</button>
    </div>

    <!-- 동아리/활동 -->
    <div class="dyn-section">
      <div class="dyn-title">동아리 / 활동</div>
      <div id="act-rows"></div>
      <button id="add-act" class="dyn-add">+ 활동 추가</button>
    </div>

    <!-- 자격증 -->
    <div class="dyn-section">
      <div class="dyn-title">자격증</div>
      <div id="cert-rows"></div>
      <button id="add-cert" class="dyn-add">+ 자격증 추가</button>
    </div>

    <!-- 업종 / 관심 분야 -->
    <div class="dyn-section">
      <div class="dyn-title">업계 / 관심 분야 <span style="font-weight:400;color:#aaa;font-size:.75rem">(복수 선택 가능)</span></div>
      <div class="tag-select-wrap" id="job-tag-select"></div>
    </div>

    <button id="modal-submit">제출하기</button>
    <div id="form-msg"></div>
  </div>
</div>
</div>
"""

HTML = (
    '<!DOCTYPE html><html lang="ko"><head>'
    '<meta charset="UTF-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
    '<title>인원 디렉토리</title>'
    '<style>' + CSS + '</style></head><body>'
    '<header>'
    '  <img src="https://www.google.com/s2/favicons?domain=knu.ac.kr&sz=64" class="knu-logo" alt="경북대">'
    '  <div class="header-title"><h1>KCIS</h1><span class="count" id="cnt"></span></div>'
    '  <input id="search" type="text" placeholder="이름·학과·회사·수상 통합 검색…">'
    '  <button id="stat-btn" class="hdr-btn">통계</button>'
    '  <button id="join-btn" class="hdr-btn">회원가입</button>'
    '</header>'
    '<div class="filter-bar" id="fbar">'
    '  <button class="fbtn active" data-filter="">전체</button>'
    '</div>'
    '<div id="grid"></div>'
    '<div id="tooltip"></div>'
    + MODAL_HTML +
    '<script>' + JS + '</script>'
    '</body></html>'
)


def main():
    global CSV_PATH
    folder = os.path.dirname(os.path.abspath(__file__))

    # 커맨드라인 인자로 파일 지정 가능: python build_site.py 파일명.csv
    if len(sys.argv) > 1:
        CSV_PATH = os.path.join(folder, sys.argv[1])
    elif not os.path.exists(CSV_PATH):
        cands = sorted([f for f in os.listdir(folder) if f.startswith('notion_') and f.endswith('.csv')])
        if not cands:
            print(f'[오류] notion_*.csv 파일을 찾을 수 없습니다.'); sys.exit(1)
        if len(cands) == 1:
            CSV_PATH = os.path.join(folder, cands[0])
        else:
            print('여러 CSV 파일이 있습니다. 사용할 파일을 선택하세요:')
            for i, f in enumerate(cands):
                print(f'  {i+1}. {f}')
            choice = input('번호 입력: ').strip()
            CSV_PATH = os.path.join(folder, cands[int(choice)-1])

    print('CSV 파싱 중...')
    persons = load_persons(CSV_PATH)
    print(f'  → {len(persons)}명 완료')

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    html = HTML.replace('__DATA_JSON__', json.dumps(persons, ensure_ascii=False))
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\n완료: {OUT_PATH}')


if __name__ == '__main__':
    main()