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
import json # [NEW] JSON 처리를 위한 모듈 추가

# ==========================================
# 👇 [필수] API 키 입력
GEMINI_API_KEY = "AIzaSyAfXO1BT9fz9Au-WkaMEPWIDIOhFbJ2pF4"
# ==========================================

# --- 1. 기본 설정 ---
st.set_page_config(page_title="연우의 단어장", page_icon="📖", layout="wide")
st.title("📖 연우의 영어 단어장")

# --- 2. 구글 시트 연결 ---
@st.cache_resource
def get_google_sheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    return gspread.authorize(creds)

# --- 3. 오디오 생성 ---
@st.cache_data(show_spinner=False)
def get_audio_bytes(word):
    try:
        time.sleep(0.1) 
        tts = gTTS(text=word, lang='en')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        return fp
    except: return None

# --- 4. 영영사전 데이터 ---
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

# --- 5. Gemini 설정 및 생성 (배치 처리로 변경) ---
def get_gemini_model():
    if not GEMINI_API_KEY: return None
    try:
                # 1순위: 최신 플래시 모델
        return genai.GenerativeModel('gemini-2.5-flash')
    except:
        try:
            # 2순위: 구버전 프로 모델 (혹시 플래시가 안되면 이거라도)
            return genai.GenerativeModel('gemini-2.5-pro')
        except:
            return None

# [NEW] 10개씩 묶어서 질문하는 함수
def generate_ai_tips_batch(word_list):
    """
    word_list 예시: [{'word': 'apple', 'meaning': '사과'}, {'word': 'run', 'meaning': '달리다'} ...]
    """
    model = get_gemini_model()
    if not model: return {}

    # 질문할 단어 목록을 텍스트로 변환
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
        각 단어마다 다음 3가지 내용을 포함해서 하나의 문단으로 자연스럽게 써줘.
        1. **상황**: 실제로 어떤 상황에서 쓰이는지
        2. **차이**: 비슷한 단어와 뉘앙스 차이 (없으면 생략 가능)
        3. **꿀팁**: 외우기 쉬운 팁(한국어) + 예문(영어)
        4. **말투**: "👉 친구랑 놀 때 자주 써요!" 처럼 친절하게 하고, 문장 맨 앞에 '👉' 이모지를 붙여줘.

        [중요: 출력 형식]
        반드시 **JSON 형식**으로만 출력해. 다른 말은 하지 마.
        Key는 '영어단어', Value는 '설명내용'이어야 해.
        예시:
        {{
            "apple": "👉 과일 가게나 간식 시간에 자주 써요! 빨간 사과를 떠올려보세요. Ex) I eat an apple.",
            "run": "👉 운동장이나 급할 때 써요! jog보다는 더 빨리 뛰는 느낌이에요. Ex) Run fast!"
        }}
        """
        
        # API 호출
        response = model.generate_content(prompt)
        text_response = response.text.strip()
        
        # 혹시 ```json ... ``` 같은 마크다운이 붙어있으면 제거
        if text_response.startswith("```json"):
            text_response = text_response.replace("```json", "").replace("```", "")
        
        # JSON 문자열을 파이썬 딕셔너리로 변환
        result_dict = json.loads(text_response)
        return result_dict

    except Exception as e:
        print(f"AI Batch Error: {e}")
        return {} # 실패하면 빈 딕셔너리 반환

# --- 6. PDF 생성 ---
def create_quiz_pdf(df, week_name):
    pdf = FPDF()
    font_path = "NanumGothic-Bold.ttf"
    try: pdf.add_font("NanumGothic", style="", fname=font_path)
    except: 
        st.error("⚠️ 'NanumGothic-Bold.ttf' 폰트 파일이 폴더에 없어요!")
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
    spreadsheet_name = "GLP_words"
    doc = client.open(spreadsheet_name)
except Exception as e:
    st.error(f"구글 시트 연결 실패: {e}")
    st.stop()

with st.sidebar:
    st.header("🗂 학습 메뉴")
    try:
        worksheets = [ws.title for ws in doc.worksheets()]
        selected_tab = st.selectbox("주차 선택", worksheets)
        st.markdown("---")
        st.markdown("**Created for Yeonu.ko.**")
        
        st.markdown("---")
        # 모델 확인용 버튼
        if st.button("🤖 내 모델 목록 확인"):
            try:
                genai.configure(api_key=GEMINI_API_KEY)
                st.write("사용 가능한 모델:")
                for m in genai.list_models():
                    if 'generateContent' in m.supported_generation_methods:
                        st.code(m.name)
            except Exception as e:
                st.error(f"목록 확인 실패: {e}")

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
            # === [수정됨] 10개씩 묶어서 처리하는 로직 ===
            if st.button("✨ AI 쌤에게 꿀팁 채워달라고 하기 (빈칸만)"):
                if not GEMINI_API_KEY:
                    st.error("⚠️ API 키가 없어요.")
                else:
                    progress_bar = st.progress(0, text="작업 대상을 찾고 있어요...")
                    
                    # 1. 작업해야 할 빈칸(Target) 찾기
                    target_rows = []
                    for index, row in df.iterrows():
                        raw_context = row.get('Context', '')
                        current_context = str(raw_context).strip()
                        
                        # 내용이 없거나 'nan'인 경우만 리스트에 추가
                        if not current_context or current_context.lower() == 'nan':
                            target_rows.append({
                                'index': index, # 데이터프레임 인덱스
                                'word': row['Word'],
                                'meaning': row['Meaning']
                            })
                    
                    if not target_rows:
                        st.success("이미 모든 단어에 설명이 적혀있어요! 👍")
                    else:
                        st.info(f"총 {len(target_rows)}개의 단어에 설명을 채울 예정입니다. (10개씩 묶어서 처리)")
                        
                        # 2. 10개씩 잘라서(Chunk) 처리하기
                        batch_size = 10
                        total_processed = 0
                        
                        for i in range(0, len(target_rows), batch_size):
                            # 이번에 처리할 묶음 (최대 10개)
                            batch = target_rows[i : i + batch_size]
                            
                            progress_bar.progress((i) / len(target_rows), text=f"AI가 {i+1}~{i+len(batch)}번째 단어를 생각 중입니다...")
                            
                            # AI에게 묶음 질문 던지기
                            # word_list만 뽑아서 전달
                            batch_response = generate_ai_tips_batch(batch)
                            
                            # 응답받은 내용을 시트에 쓰기
                            for item in batch:
                                word_key = item['word']
                                # AI 응답에 해당 단어가 있으면 저장
                                if word_key in batch_response:
                                    explanation = batch_response[word_key]
                                    try:
                                        # 구글 시트 D열(4번째)에 업데이트
                                        sheet.update_cell(item['index'] + 2, 4, explanation)
                                        total_processed += 1
                                    except Exception as e:
                                        print(f"저장 실패: {e}")
                                else:
                                    print(f"AI 응답 누락: {word_key}")
                            
                            # 묶음 처리 후 1초 휴식 (너무 빠르면 차단될 수 있음)
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
                        audio = get_audio_bytes(word)
                        if audio: st.audio(audio, format='audio/mp3')
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