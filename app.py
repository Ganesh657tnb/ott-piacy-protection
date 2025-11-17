import os
import wave
import struct
import streamlit as st
import tempfile
import subprocess

# Configuration
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# FFmpeg path (Streamlit Cloud)
FFMPEG_BIN = "/usr/bin/ffmpeg"

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

# Extract audio from video
def extract_audio_ffmpeg(video_path, output_wav_path):
    subprocess.run([
        FFMPEG_BIN, "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", output_wav_path
    ], check=True)

# Convert WAV to MP3
def convert_wav_to_mp3(wav_path, mp3_path):
    subprocess.run([
        FFMPEG_BIN, "-y", "-i", wav_path, mp3_path
    ], check=True)

# Re-insert audio into video
def insert_audio_ffmpeg(video_path, audio_path, output_video_path):
    subprocess.run([
        FFMPEG_BIN, "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        output_video_path
    ], check=True)

# Process video: extract audio, watermark, re-insert
def process_video_for_download(video_path, user_id):
    with tempfile.TemporaryDirectory() as temp_dir:
        # Step 1: Extract WAV audio
        temp_audio_wav = os.path.join(temp_dir, "temp_audio.wav")
        extract_audio_ffmpeg(video_path, temp_audio_wav)

        # Step 2: Watermark WAV
        watermarked_audio_wav = os.path.join(temp_dir, "watermarked_audio.wav")
        embed_watermark(temp_audio_wav, str(user_id), watermarked_audio_wav)

        # Step 3: Convert to MP3 for video compatibility
        watermarked_audio_mp3 = os.path.join(temp_dir, "watermarked_audio.mp3")
        convert_wav_to_mp3(watermarked_audio_wav, watermarked_audio_mp3)

        # Step 4: Re-insert watermarked audio
        processed_video_path = os.path.join(temp_dir, "processed_video.mp4")
        insert_audio_ffmpeg(video_path, watermarked_audio_mp3, processed_video_path)

        return processed_video_path

# Streamlit App
def main():
    st.title("Simple OTT Video App")

    # Session state
    if 'users' not in st.session_state:
        st.session_state.users = {}
    if 'logged_in_user' not in st.session_state:
        st.session_state.logged_in_user = None

    # Sidebar: Login/Register
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
                        st.session_state.users[username] = {'password': password, 'id': user_id}
                        st.success("Registered successfully! Please login.")
                elif auth_mode == "Login":
                    if username in st.session_state.users and st.session_state.users[username]['password'] == password:
                        st.session_state.logged_in_user = username
                        st.success("Logged in!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials")

    if not st.session_state.logged_in_user:
        st.warning("Please log in to access the app.")
        return

    user_id = st.session_state.users[st.session_state.logged_in_user]['id']

    # Upload Video
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
