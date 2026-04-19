"""
server.py - 디렉토리 웹서버 + LinkedIn 스크래핑 + 회원 데이터 관리
실행: python server.py
접속: http://localhost:5000  (로컬)  또는  http://localhost:7860  (HF Spaces)
"""

import asyncio, json, os, random, threading
from flask import Flask, request, jsonify, send_from_directory

# Playwright는 로컬 전용 — 클라우드 환경에서는 import 실패를 무시
try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False

BASE         = os.path.dirname(__file__)
SITE_DIR     = os.path.join(BASE, 'directory_site')
MEMBERS_FILE = os.path.join(BASE, 'members.json')
SESSION_PATH = os.path.join(BASE, 'session.json')

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

app = Flask(__name__, static_folder=SITE_DIR)

# ── LinkedIn 추출 JS ──────────────────────────────────────────────
EXTRACT_JS = """() => {
    const name = document.title.split(' | ')[0].trim();
    const lines = document.body.innerText.split('\\n').map(l=>l.trim()).filter(l=>l.length>0);
    let profileStart=0,cnt=0;
    for(let i=0;i<lines.length;i++){
        if(lines[i]===name){cnt++;if(cnt>=2){profileStart=i;break;}}
    }
    const pLines=lines.slice(profileStart);
    const title=pLines[1]||'';
    const skip=new Set(['더 보기','간략히','메시지','1촌 맺기','팔로우','연락처',
                        'Contact info','소개','·','팔로워']);
    let location='';
    for(let i=2;i<Math.min(pLines.length,20);i++){
        const l=pLines[i];
        if(!skip.has(l)&&l.length<60&&!/^\\d/.test(l)&&!l.includes('프리미엄')&&l!==title){
            location=l.replace(/\\s*·\\s*(연락처|Contact info).*/,'').trim();break;
        }
    }
    const ciIdx=pLines.findIndex(l=>l==='연락처'||l==='Contact info');
    let company='',school='';
    if(ciIdx>=0){
        const after=pLines.slice(ciIdx+1).filter(l=>l!=='·'&&l.length>1&&!/^\\d/.test(l)&&!skip.has(l));
        company=after[0]||'';school=after[1]||'';
    }
    const SECT=new Set(['소개','About','활동','Activity','경력','Experience','학력','Education',
                        '보유 기술','기술','Skills','자격증','Licenses & certifications',
                        '추천','봉사 활동','언어','관심사','더 많은 프로필']);
    function getSection(headers){
        const si=pLines.findIndex(l=>headers.includes(l));
        if(si===-1)return'';
        let ei=pLines.length;
        for(let i=si+1;i<pLines.length;i++){if(SECT.has(pLines[i])){ei=i;break;}}
        return pLines.slice(si+1,ei).filter(l=>!skip.has(l)&&l!=='·').join(' | ');
    }
    const about=getSection(['소개','About']);
    const skills=getSection(['보유 기술','기술','Skills']).replace(/\\s*•\\s*/g,' | ');
    const experience=getSection(['경력','Experience']);
    const education=getSection(['학력','Education']);
    const certs=getSection(['자격증','Licenses & certifications']);
    return {name,title,location,company,school,about,skills,experience,education,certs};
}"""


# ── LinkedIn 스크래핑 ──────────────────────────────────────────────
async def _scrape(url: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            storage_state=SESSION_PATH,
            user_agent=UA,
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(random.uniform(6, 8))

        total = await page.evaluate("document.body.scrollHeight")
        pos = 0
        while pos < total:
            pos = min(pos + 800, total)
            await page.evaluate(f"window.scrollTo(0,{pos})")
            await asyncio.sleep(0.4)
            total = await page.evaluate("document.body.scrollHeight")

        await page.evaluate("""() => {
            const T=new Set(['더 보기','모두 표시','Show more','See more','See all']);
            document.querySelectorAll('button').forEach(b=>{if(T.has(b.innerText.trim()))b.click();});
        }""")
        await asyncio.sleep(2)

        data = await page.evaluate(EXTRACT_JS)
        data['url'] = url
        await browser.close()
        return data


# ── 로그인 세션 생성 (브라우저 자동 감지) ─────────────────────────
_login_status = {'state': 'idle', 'msg': ''}

async def _do_login():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, slow_mo=50)
            ctx = await browser.new_context(user_agent=UA)
            page = await ctx.new_page()
            await page.goto('https://www.linkedin.com/login')
            _login_status['msg'] = '브라우저에서 LinkedIn에 로그인해주세요.'

            # 로그인 완료될 때까지 2초마다 URL 확인 (최대 5분)
            for _ in range(150):
                await asyncio.sleep(2)
                url = page.url
                # 로그인 페이지·체크포인트가 아닌 linkedin.com 페이지면 완료로 간주
                if ('linkedin.com' in url
                        and 'login' not in url
                        and 'authwall' not in url
                        and 'checkpoint' not in url
                        and 'signup' not in url):
                    state = await ctx.storage_state()
                    with open(SESSION_PATH, 'w', encoding='utf-8') as f:
                        json.dump(state, f, ensure_ascii=False, indent=2)
                    _login_status['state'] = 'done'
                    _login_status['msg'] = '로그인 완료! 브라우저를 닫습니다.'
                    await browser.close()   # 브라우저 자동 종료
                    return

            _login_status['state'] = 'timeout'
            _login_status['msg'] = '5분 초과. 다시 시도해주세요.'
            await browser.close()
    except Exception as e:
        _login_status['state'] = 'error'
        _login_status['msg'] = str(e)


def _run_login():
    asyncio.run(_do_login())


# ── API 라우트 ─────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(SITE_DIR, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(SITE_DIR, path)

@app.route('/api/session-status')
def session_status():
    if not _PLAYWRIGHT_OK:
        return jsonify({'exists': False, 'cloud': True})
    return jsonify({'exists': os.path.exists(SESSION_PATH)})

@app.route('/api/login', methods=['POST'])
def start_login():
    if not _PLAYWRIGHT_OK:
        return jsonify({'status': 'error', 'msg': '클라우드 환경에서는 LinkedIn 로그인을 지원하지 않습니다'}), 503
    if _login_status['state'] == 'running':
        return jsonify({'status': 'running', 'msg': '브라우저가 이미 열려있습니다'})
    _login_status['state'] = 'running'
    _login_status['msg'] = '브라우저를 여는 중...'
    t = threading.Thread(target=_run_login, daemon=True)
    t.start()
    return jsonify({'status': 'started'})

@app.route('/api/login/status')
def login_status_check():
    return jsonify(_login_status)

@app.route('/api/scrape')
def scrape():
    if not _PLAYWRIGHT_OK:
        return jsonify({'error': '클라우드 환경에서는 스크래핑을 지원하지 않습니다'}), 503
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL을 입력하세요'}), 400
    if not os.path.exists(SESSION_PATH):
        return jsonify({'error': 'session.json 없음. 먼저 LinkedIn 로그인을 해주세요'}), 400
    try:
        data = asyncio.run(_scrape(url))
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/members', methods=['GET'])
def get_members():
    if os.path.exists(MEMBERS_FILE):
        with open(MEMBERS_FILE, encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route('/api/members', methods=['POST'])
def add_member():
    data = request.json
    if not data or not data.get('name'):
        return jsonify({'error': '이름은 필수입니다'}), 400
    members = []
    if os.path.exists(MEMBERS_FILE):
        with open(MEMBERS_FILE, encoding='utf-8') as f:
            members = json.load(f)
    for i, m in enumerate(members):
        if m.get('name') == data['name']:
            members[i] = data
            break
    else:
        members.append(data)
    with open(MEMBERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(members, f, ensure_ascii=False, indent=2)
    return jsonify({'ok': True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"서버 시작: http://localhost:{port}")
    app.run(debug=False, host='0.0.0.0', port=port)