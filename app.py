import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
# gTTS 등은 필요 없지만 에러 방지용 import
import io
import requests
from fpdf import FPDF
import math
from pathlib import Path
import random
import time
import google.generativeai as genai
import json

# --- 1. 기본 설정 ---
st.set_page_config(page_title="연우의 단어장", page_icon="📖", layout="wide")
st.title("📖 연우의 단어장")

# --- 2. 비밀 정보(Secrets) 가져오기 ---
GEMINI_API_KEY = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    GEMINI_API_KEY = "AIzaSyAfXO1BT9fz9Au-WkaMEPWIDIOhFbJ2pF4" 

# --- 3. 구글 시트 연결 ---
@st.cache_resource
def get_google_sheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        except:
            st.error("❌ 'service_account.json' 파일을 찾을 수 없거나 Secrets 설정이 안 되어 있습니다.")
            return None
            
    return gspread.authorize(creds)

# --- 4. 오디오 생성 (버튼 스타일 수정) ---
def get_audio_html(word):
    safe_word = word.replace("'", "").replace('"', "")
    
    # 버튼 디자인을 '이모지' 느낌으로 작고 깔끔하게 수정했습니다.
    html_code = f"""
    <html>
    <body>
        <script>
            function speak_{safe_word.replace(" ", "_")}() {{
                const msg = new SpeechSynthesisUtterance();
                msg.text = "{safe_word}";
                msg.lang = "en-US";
                msg.rate = 0.8;
                window.speechSynthesis.speak(msg);
            }}
        </script>
        <button onclick="speak_{safe_word.replace(" ", "_")}()" style="
            background-color: transparent; 
            border: 1px solid #ddd; 
            color: #333; 
            padding: 2px 8px; 
            text-align: center; 
            display: inline-block; 
            font-size: 18px; 
            margin: 0px; 
            cursor: pointer; 
            border-radius: 50%;
            line-height: 1.5;">
            🔊
        </button>
    </body>
    </html>
    """
    return html_code

# --- 5. 영영사전 데이터 ---
@st.cache_data(show_spinner=False)
def get_dictionary_data(word):
    clean_word = word.strip().lower()
    api_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{clean_word}"
    headers = { "User-Agent": "Mozilla/5.0" }
    try:
        time.sleep(0.2) 
        response = requests.get(api_url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            try:
                meaning = data[0]['meanings'][0]['definitions'][0].get('definition', '')
                example = data[0]['meanings'][0]['definitions'][0].get('example', '')
                return meaning, example
            except: return None, None
        else: return None, None
    except: return None, None

# --- 6. Gemini 설정 ---
def get_gemini_model():
    if not GEMINI_API_KEY: return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel('gemini-2.5-flash')
    except:
        try:
            return genai.GenerativeModel('gemini-2.5-pro')
        except:
            return None

def generate_ai_tips_batch(word_list):
    model = get_gemini_model()
    if not model: return {}

    words_str = ""
    for item in word_list:
        words_str += f"- {item['word']} (뜻: {item['meaning']})\n"

    try:
        prompt = f"""
        너는 중학생 영어를 가르치는 친절한 선생님이야.
        아래 영단어 목록(약 10개)에 대해, 각각 아이가 이해하기 쉬운 설명을 만들어줘.

        [단어 목록]
        {words_str}

        [설명 작성 규칙]
        각 단어마다 다음의 내용을 포함해서 자연스럽게 써줘. 
        1. **상황**: 실제로 어떤 상황에서 쓰이는지
        2. **차이**: 비슷한 단어와 뉘앙스 차이 (없으면 생략 가능)
        3. **꿀팁**: 외우기 쉬운 팁(한국어) + 예문(영어)
        4. **말투**: "👉 친구랑 놀 때 자주 써요!" 처럼 친절하게 하고, 문장 맨 앞에 '👉' 이모지를 붙여줘. 👉로 시작하는 문장은 앞의 문장과 줄바꿈 처리를 꼭 해줘.

        [중요: 출력 형식]
        반드시 **JSON 형식**으로만 출력해.
        Key는 '영어단어', Value는 '설명내용'이어야 해.
        이 형식을 꼭 지켜줘.
        예시:
        {{
            "apple": "👉 과일 가게나 간식 시간에 자주 써요! 빨간 사과를 떠올려보세요. Ex) I eat an apple.",
            "run": "👉 운동장이나 급할 때 써요! jog보다는 더 빨리 뛰는 느낌이에요. Ex) Run fast!"
        }}
        """
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        if text_response.startswith("```json"):
            text_response = text_response.replace("```json", "").replace("```", "")
        result_dict = json.loads(text_response)
        return result_dict

    except Exception as e:
        print(f"AI Batch Error: {e}")
        return {} 

# --- 7. PDF 생성 ---
def create_quiz_pdf(df, week_name, items_per_set=10):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=10)
    font_path = Path(__file__).resolve().parent / "NanumGothic-Bold.ttf"
    try:
        pdf.add_font("NanumGothic", style="", fname=str(font_path))
    except: 
        st.error("⚠️ 'NanumGothic-Bold.ttf' 폰트 파일이 폴더에 없어요!")
        return None

    pdf.set_font("NanumGothic", size=12)

    total_words = len(df)
    if total_words == 0:
        return None

    set_count = max(1, math.ceil(total_words / items_per_set))

    for i in range(1, set_count + 1):
        set_start = (i - 1) * items_per_set
        set_end = i * items_per_set
        set_df = df.iloc[set_start:set_end]
        if set_df.empty:
            continue

        pdf.add_page()
        pdf.set_font("NanumGothic", size=16)
        pdf.cell(0, 15, f"영어 단어 테스트 - {week_name} (Set {i})", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("NanumGothic", size=10)
        pdf.cell(0, 10, f"이름: ____________________   점수: ___________", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        shuffled_df = set_df.sample(frac=1).reset_index(drop=True)
        pdf.set_font("NanumGothic", size=11)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(15, 10, "No.", border=1, align="C", fill=True)
        pdf.cell(80, 10, "Word (영어)", border=1, align="C", fill=True)
        pdf.cell(95, 10, "Meaning (뜻)", border=1, align="C", fill=True)
        pdf.ln()

        for idx, row in shuffled_df.iterrows():
            word = str(row['Word'])
            meaning = str(row['Meaning'])
            quiz_type = random.choice([0, 1])
            pdf.cell(15, 12, str(idx + 1), border=1, align="C")
            pdf.cell(80, 12, "" if quiz_type == 0 else word, border=1, align="L")
            pdf.cell(95, 12, "" if quiz_type == 1 else meaning, border=1, align="L")
            pdf.ln()

    pdf.add_page()
    pdf.set_font("NanumGothic", size=16)
    pdf.cell(0, 15, f"최종 확인 학습 (전체 단어) - {week_name}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("NanumGothic", size=10)
    pdf.cell(0, 10, "영어 단어를 모두 적어보세요!", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    pdf.set_font("NanumGothic", size=11)
    pdf.set_fill_color(220, 230, 240)
    pdf.cell(15, 10, "No.", border=1, align="C", fill=True)
    pdf.cell(80, 10, "Word (쓰기)", border=1, align="C", fill=True)
    pdf.cell(95, 10, "Meaning (뜻)", border=1, align="C", fill=True)
    pdf.ln()

    for idx, row in df.iterrows():
        pdf.cell(15, 12, str(idx + 1), border=1, align="C")
        pdf.cell(80, 12, "", border=1, align="L")
        pdf.cell(95, 12, str(row['Meaning']), border=1, align="L")
        pdf.ln()

    return bytes(pdf.output())

# --- 메인 로직 ---
try:
    client = get_google_sheet_client()
    if not client: st.stop()
    
    spreadsheet_name = "GLP_words"
    doc = client.open(spreadsheet_name)
except Exception as e:
    st.error(f"구글 시트 연결 실패: {e}")
    st.info("💡 Secrets 또는 service_account.json을 확인하세요.")
    st.stop()

with st.sidebar:
    st.header("🗂 학습 메뉴")
    try:
        worksheets = [ws.title for ws in doc.worksheets()]
        selected_tab = st.selectbox("주차 선택", worksheets)
        st.markdown("---")
        st.markdown("**Created for Yeonu.ko.**")
    except: st.stop()

try:
    sheet = doc.worksheet(selected_tab)
    header_row = sheet.row_values(1)
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df = df.fillna("")

    # --- 컬럼명 정규화 (시트마다 헤더가 다를 수 있음) ---
    col_map = {}
    if "Word" in df.columns:
        col_map["Word"] = "Word"
    elif "World" in df.columns:  # 오타 대응
        col_map["World"] = "Word"

    if "Meaning" in df.columns:
        col_map["Meaning"] = "Meaning"
    elif "Meaning_ko" in df.columns:
        col_map["Meaning_ko"] = "Meaning"

    if col_map:
        df = df.rename(columns=col_map)

    if 'Context' not in df.columns:
        df['Context'] = ""

    if "Context" in header_row:
        context_col_index = header_row.index("Context") + 1
    else:
        context_col_index = None

    if df.empty:
        st.warning("단어가 없어요!")
    else:
        tab1, tab2 = st.tabs(["📚 단어 공부하기", "🖨️ 시험지 만들기"])

        with tab1:
            # === AI 꿀팁 생성 버튼 ===
            if st.button("✨ AI 쌤에게 꿀팁 채워달라고 하기 (빈칸만)"):
                if not GEMINI_API_KEY or "API_키" in GEMINI_API_KEY:
                    st.error("⚠️ API 키가 설정되지 않았습니다.")
                elif context_col_index is None:
                    st.error("⚠️ 시트에 'Context' 헤더가 없습니다. 헤더를 추가한 뒤 다시 시도하세요.")
                else:
                    progress_bar = st.progress(0, text="작업 대상을 찾고 있어요...")
                    target_rows = []
                    for index, row in df.iterrows():
                        raw_context = row.get('Context', '')
                        current_context = str(raw_context).strip()
                        if not current_context or current_context.lower() == 'nan':
                            target_rows.append({
                                'index': index,
                                'word': row['Word'],
                                'meaning': row['Meaning']
                            })
                    
                    if not target_rows:
                        st.success("이미 모든 단어에 설명이 적혀있어요! 👍")
                    else:
                        st.info(f"총 {len(target_rows)}개의 단어에 설명을 채울 예정입니다. (10개씩 묶어서 처리)")
                        batch_size = 10
                        total_processed = 0
                        
                        for i in range(0, len(target_rows), batch_size):
                            batch = target_rows[i : i + batch_size]
                            progress_bar.progress((i) / len(target_rows), text=f"AI가 생각 중... ({i+1}~{i+len(batch)})")
                            
                            batch_response = generate_ai_tips_batch(batch)
                            
                            for item in batch:
                                # 모델이 대소문자를 다르게 반환할 수 있으니 소문자로 매칭
                                key = item['word'].strip().lower()
                                matched = None
                                if key in batch_response:
                                    matched = batch_response[key]
                                else:
                                    # 원문 키도 함께 시도
                                    if item['word'] in batch_response:
                                        matched = batch_response[item['word']]
                                if matched:
                                    try:
                                        sheet.update_cell(item['index'] + 2, context_col_index, matched)
                                        total_processed += 1
                                    except Exception as e:
                                        print(f"저장 실패: {e}")
                            time.sleep(1)

                        progress_bar.empty()
                        st.success(f"완료! 총 {total_processed}개의 설명을 새로 적었습니다.")
                        time.sleep(2)
                        st.rerun()

            st.info("💡 단어를 클릭하고 설명을 읽어보세요!")
            
            my_bar = st.progress(0, text="로딩 중...")
            total_words = len(df)

            # =========================================================
            # 👇 [UI 수정됨] 단어 표시 부분 
            # =========================================================
            for index, row in df.iterrows():
                my_bar.progress((index + 1) / total_words)
                
                word = str(row['Word'])
                kor_meaning = row['Meaning']
                context_tip = str(row.get('Context', ''))
                eng_def, eng_ex = get_dictionary_data(word)

                # 1. 단어 카드 컨테이너
                with st.container():
                    # 3개의 컬럼으로 분할 (단어 / 오디오 / 한글뜻)
                    # 비율 조절: [단어(2), 오디오(0.5), 한글뜻(4)]
                    c1, c2, c3 = st.columns([1.5, 0.5, 4])
                    
                    with c1:
                        # 영어 단어 (크게)
                        st.markdown(f"#### **{index + 1}. {word}**")
                    
                    with c2:
                        # 오디오 버튼 (단어 바로 옆)
                        audio_html = get_audio_html(word)
                        # components.html을 쓰면 iframe이라 높이 조절 필요
                        st.components.v1.html(audio_html, height=35)
                    
                    with c3:
                         # 한글 뜻 (수직 중앙 정렬 느낌을 위해 마크다운 사용)
                        st.markdown(f"#### :blue[{kor_meaning}]")

                    # 2. 영영사전 뜻 (아래쪽에 살짝 들여쓰기)
                    if eng_def:
                        st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;↳ 🇺🇸 *{eng_def}*")
                        if eng_ex:
                            st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;ex) {eng_ex}")

                    # 3. AI 꿀팁 (접이식 박스 - Expander)
                    # 내용이 있을 때만 표시
                    if context_tip and context_tip.lower() != 'nan':
                        # 'expanded=False'는 기본적으로 닫혀있게 함
                        with st.expander("💡 AI 쌤의 꿀팁 보기 (클릭)", expanded=False):
                            st.info(context_tip)

                # 구분선
                st.markdown("---")
            
            my_bar.empty()

        with tab2:
            st.header("📝 랜덤 테스트지 생성")
            if st.button("🚀 시험지 PDF 만들기"):
                with st.spinner("PDF 생성 중..."):
                    pdf_data = create_quiz_pdf(df, selected_tab)
                    if pdf_data:
                        st.success("완료!")
                        st.download_button("📥 PDF 다운로드", pdf_data, f"{selected_tab}_quiz.pdf", "application/pdf")

except Exception as e:
    st.error(f"오류: {e}")
