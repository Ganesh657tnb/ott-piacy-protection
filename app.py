import os
import wave
import struct
import streamlit as st
from moviepy.editor import VideoFileClip, AudioFileClip
from pydub import AudioSegment
import tempfile

# Configuration
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Watermarking function (unchanged, operates on WAV)
def embed_watermark(input_wav, watermark_text, output_wav):
    with wave.open(input_wav, "rb") as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)

    samples = list(struct.unpack("<" + "h" * (len(frames) // 2), frames))

    watermark_bits = ''.join(format(ord(c), '08b') for c in watermark_text)
    length_bits = format(len(watermark_bits), '016b')  # 16 bits for length

    final_bits = length_bits + watermark_bits

    for i, bit in enumerate(final_bits):
        if i < len(samples):
            samples[i] = (samples[i] & ~1) | int(bit)

    new_frames = struct.pack("<" + "h" * len(samples), *samples)

    with wave.open(output_wav, "wb") as wav_out:
        wav_out.setparams(params)
        wav_out.writeframes(new_frames)

    return output_wav

# Function to process video: extract audio as WAV, watermark WAV, convert to MP3 for re-insertion
def process_video_for_download(video_path, user_id):
    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract audio as WAV (intermediate format)
        video_clip = VideoFileClip(video_path)
        audio_clip = video_clip.audio
        temp_audio_wav = os.path.join(temp_dir, "temp_audio.wav")
        audio_clip.write_audiofile(temp_audio_wav, codec="pcm_s16le")  # Export as WAV
        video_clip.close()
        audio_clip.close()

        # Watermark the WAV audio directly
        watermarked_audio_wav = os.path.join(temp_dir, "watermarked_audio.wav")
        embed_watermark(temp_audio_wav, str(user_id), watermarked_audio_wav)

        # Convert watermarked WAV to MP3 for video compatibility (intermediate step before re-insertion)
        watermarked_audio_mp3 = os.path.join(temp_dir, "watermarked_audio.mp3")
        sound = AudioSegment.from_wav(watermarked_audio_wav)
        sound.export(watermarked_audio_mp3, format="mp3")

        # Re-insert watermarked audio (now MP3) into video
        video_clip_no_audio = VideoFileClip(video_path).set_audio(None)
        watermarked_audio_clip = AudioFileClip(watermarked_audio_mp3)
        final_clip = video_clip_no_audio.set_audio(watermarked_audio_clip)
        processed_video_path = os.path.join(temp_dir, "processed_video.mp4")
        final_clip.write_videofile(processed_video_path, codec="libx264", audio_codec="aac")
        final_clip.close()
        watermarked_audio_clip.close()

        return processed_video_path

# Streamlit App
def main():
    st.title("Simple OTT Video App")

    # Initialize session state for users and login
    if 'users' not in st.session_state:
        st.session_state.users = {}  # In-memory user storage: {username: {'password': str, 'id': int}}
    if 'logged_in_user' not in st.session_state:
        st.session_state.logged_in_user = None

    # Sidebar for login/registration
    with st.sidebar:
        st.header("Authentication")
        if st.session_state.logged_in_user:
            st.write(f"Logged in as: {st.session_state.logged_in_user}")
            if st.button("Logout"):
                st.session_state.logged_in_user = None
                st.rerun()
        else:
            auth_mode = st.radio("Choose:", ["Login", "Register"])
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.button("Submit"):
                if auth_mode == "Register":
                    if username in st.session_state.users:
                        st.error("Username already exists")
                    else:
                        user_id = len(st.session_state.users) + 1
                        st.session_state.users[username] = {'password': password, 'id': user_id}  # Plain text for demo
                        st.success("Registered successfully! Please login.")
                elif auth_mode == "Login":
                    if username in st.session_state.users and st.session_state.users[username]['password'] == password:
                        st.session_state.logged_in_user = username
                        st.success("Logged in!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials")

    # Main content (only if logged in)
    if not st.session_state.logged_in_user:
        st.warning("Please log in to access the app.")
        return

    user_id = st.session_state.users[st.session_state.logged_in_user]['id']

    # Upload Section
    st.header("Upload Video")
    uploaded_file = st.file_uploader("Choose a video file", type=list(ALLOWED_EXTENSIONS))
    if uploaded_file and st.button("Upload"):
        filename = uploaded_file.name
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"Uploaded {filename}")

    # List and Download Videos
    st.header("Available Videos")
    videos = [f for f in os.listdir(UPLOAD_FOLDER) if f.split('.')[-1].lower() in ALLOWED_EXTENSIONS]
    if videos:
        for video in videos:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(video)
            with col2:
                if st.button(f"Download {video}", key=video):
                    video_path = os.path.join(UPLOAD_FOLDER, video)
                    with st.spinner("Processing video (extracting, watermarking WAV, re-inserting audio)..."):
                        processed_path = process_video_for_download(video_path, user_id)
                    with open(processed_path, "rb") as f:
                        st.download_button(
                            label="Download Processed Video",
                            data=f,
                            file_name=f"watermarked_{video}",
                            mime="video/mp4",
                            key=f"download_{video}"
                        )
    else:
        st.write("No videos uploaded yet.")

if __name__ == "__main__":
    main()
