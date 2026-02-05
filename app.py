import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from gtts import gTTS
import io
import requests
from fpdf import FPDF
import random
import time
import google.generativeai as genai
import json

# --- 1. 기본 설정 ---
st.set_page_config(page_title="연우의 단어장", page_icon="📖", layout="wide")
st.title("📖 연우의 영어 단어장")

# --- 2. 비밀 정보(Secrets) 가져오기 ---
# 로컬(내 컴퓨터)과 클라우드(Streamlit Cloud) 환경을 모두 지원하도록 설정
GEMINI_API_KEY = None
try:
    if "GEMINI_API_KEY" in st.secrets:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    # 로컬 테스트용: secrets.toml 파일이 없으면 코드에 적힌 키 사용 (테스트 할 때만 사용하세요)
    # GitHub에 올릴 때는 이 부분을 비워두거나 주의해야 합니다.
    GEMINI_API_KEY = "AIzaSyAfXO1BT9fz9Au-WkaMEPWIDIOhFbJ2pF4" 

# --- 3. 구글 시트 연결 (보안 강화) ---
@st.cache_resource
def get_google_sheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 1. Streamlit Cloud 배포 환경 (Secrets 사용)
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    
    # 2. 내 컴퓨터 로컬 환경 (파일 사용)
    else:
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        except:
            st.error("❌ 'service_account.json' 파일을 찾을 수 없거나 Secrets 설정이 안 되어 있습니다.")
            return None
            
    return gspread.authorize(creds)

# --- 4. 오디오 생성 ---
# 서버가 파일을 만드는게 아니라, 브라우저가 직접 재생하는 HTML 코드를 만듭니다.
def get_audio_html(word):
    # 구글 번역기의 숨겨진 음성 API 주소 (클라이언트 사이드 재생)
    audio_url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={word}&tl=en&client=tw-ob"
    
    # HTML audio 태그 생성
    html_code = f"""
        <audio controls style="width: 100%;">
            <source src="{audio_url}" type="audio/mpeg">
            Your browser does not support the audio element.
        </audio>
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

# --- 6. Gemini 설정 (모델 2.5 고정) ---
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
    """
    10개씩 묶어서 질문하고 JSON으로 결과를 받는 함수
    """
    model = get_gemini_model()
    if not model: return {}

    # 질문할 단어 목록 텍스트 변환
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
        
        # 마크다운 제거
        if text_response.startswith("```json"):
            text_response = text_response.replace("```json", "").replace("```", "")
        
        result_dict = json.loads(text_response)
        return result_dict

    except Exception as e:
        print(f"AI Batch Error: {e}")
        return {} 

# --- 7. PDF 생성 ---
def create_quiz_pdf(df, week_name):
    pdf = FPDF()
    # [중요] 폰트 파일이 같은 폴더에 있어야 함
    font_path = "NanumGothic-Bold.ttf"
    try: pdf.add_font("NanumGothic", style="", fname=font_path)
    except: 
        st.error("⚠️ 'NanumGothic-Bold.ttf' 폰트 파일이 폴더에 없어요! GitHub에 같이 올렸는지 확인해주세요.")
        return None

    pdf.set_font("NanumGothic", size=12)

    # 1~5페이지
    for i in range(1, 6):
        pdf.add_page()
        pdf.set_font("NanumGothic", size=16)
        pdf.cell(0, 15, f"영어 단어 테스트 - {week_name} (Set {i})", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("NanumGothic", size=10)
        pdf.cell(0, 10, f"이름: ____________________   점수: ___________", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        shuffled_df = df.sample(frac=1).reset_index(drop=True)
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

    # 6페이지
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
    if not client: st.stop() # 연결 실패 시 중단
    
    spreadsheet_name = "GLP_words"
    doc = client.open(spreadsheet_name)
except Exception as e:
    st.error(f"구글 시트 연결 실패: {e}")
    st.info("💡 팁: 로컬에서는 'service_account.json' 파일이 필요하고, Streamlit Cloud에서는 Secrets 설정이 필요합니다.")
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
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    
    # 데이터 청소
    df = df.fillna("") 
    if 'Context' not in df.columns: df['Context'] = ""

    if df.empty:
        st.warning("단어가 없어요!")
    else:
        tab1, tab2 = st.tabs(["📚 단어 공부하기", "🖨️ 시험지 만들기"])

        with tab1:
            # === AI 꿀팁 생성 버튼 ===
            if st.button("✨ AI 쌤에게 꿀팁 채워달라고 하기 (빈칸만)"):
                if not GEMINI_API_KEY or "API_키" in GEMINI_API_KEY:
                    st.error("⚠️ API 키가 설정되지 않았습니다. (Secrets 설정을 확인하세요)")
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
                            progress_bar.progress((i) / len(target_rows), text=f"AI가 {i+1}~{i+len(batch)}번째 단어를 생각 중입니다...")
                            
                            batch_response = generate_ai_tips_batch(batch)
                            
                            for item in batch:
                                word_key = item['word']
                                if word_key in batch_response:
                                    explanation = batch_response[word_key]
                                    try:
                                        # D열(4번째)에 업데이트
                                        sheet.update_cell(item['index'] + 2, 4, explanation)
                                        total_processed += 1
                                    except Exception as e:
                                        print(f"저장 실패: {e}")
                                else:
                                    print(f"AI 응답 누락: {word_key}")
                            
                            time.sleep(1)

                        progress_bar.empty()
                        st.success(f"완료! 총 {total_processed}개의 설명을 새로 적었습니다.")
                        time.sleep(2)
                        st.rerun()

            st.info("💡 단어를 클릭하고 설명을 읽어보세요!")
            
            my_bar = st.progress(0, text="단어 정보를 불러오는 중...")
            total_words = len(df)

            for index, row in df.iterrows():
                my_bar.progress((index + 1) / total_words)
                
                word = str(row['Word'])
                kor_meaning = row['Meaning']
                context_tip = str(row.get('Context', ''))
                
                eng_def, eng_ex = get_dictionary_data(word)

                with st.container():
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.subheader(f"{index + 1}. {word}")
                        
                        audio = get_audio_html(word)
                        # if audio: st.audio(audio, format='audio/mp3')
                        st.markdown(audio_html, unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"🇰🇷 **{kor_meaning}**")
                        
                        if context_tip and context_tip.lower() != 'nan':
                            st.info(f"{context_tip}")
                        
                        if eng_def:
                            st.markdown(f"🇺🇸 *{eng_def}*")
                            if eng_ex: st.caption(f"ex) {eng_ex}")
                    st.markdown("---")
            my_bar.empty()

        with tab2:
            st.header("📝 랜덤 테스트지 생성")
            st.write("마지막 장은 전체 단어 쓰기 테스트입니다.")
            if st.button("🚀 시험지 PDF 만들기"):
                with st.spinner("PDF 생성 중..."):
                    pdf_data = create_quiz_pdf(df, selected_tab)
                    if pdf_data:
                        st.success("완료!")
                        st.download_button("📥 PDF 다운로드", pdf_data, f"{selected_tab}_quiz.pdf", "application/pdf")

except Exception as e:
    st.error(f"오류: {e}")