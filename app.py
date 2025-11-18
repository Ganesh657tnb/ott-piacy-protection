import os
import wave
import struct
import streamlit as st
from pydub import AudioSegment
import tempfile
import subprocess
from io import BytesIO

# --- Configuration & Setup ---
# Note: In a deployed environment, relying on the local filesystem (UPLOAD_FOLDER) 
# is highly discouraged as it's not persistent and shared by all users.
UPLOAD_FOLDER = 'uploads/'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- Watermarking Functions (LSB on WAV) ---

# Watermarking function (unchanged, operates on WAV)
def embed_watermark(input_wav, watermark_text, output_wav):
    """Embeds a watermark (user ID) into the least significant bit of the WAV audio samples."""
    with wave.open(input_wav, "rb") as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)

    samples = list(struct.unpack("<" + "h" * (len(frames) // 2), frames))
    watermark_bits = ''.join(format(ord(c), '08b') for c in watermark_text)
    length_bits = format(len(watermark_bits), '016b')
    final_bits = length_bits + watermark_bits

    # Ensure the audio is long enough for the watermark
    if len(final_bits) > len(samples):
        raise ValueError("Audio is too short to embed the full watermark.")

    for i, bit in enumerate(final_bits):
        samples[i] = (samples[i] & ~1) | int(bit)

    new_frames = struct.pack("<" + "h" * len(samples), *samples)
    with wave.open(output_wav, "wb") as wav_out:
        wav_out.setparams(params)
        wav_out.writeframes(new_frames)

    return output_wav

# --- FFmpeg Utilities ---
# Note: FFmpeg must be installed and accessible in the PATH for these to work.

def extract_audio_ffmpeg(video_path, output_wav_path):
    """Extracts audio from video to a temporary WAV file."""
    # -y: overwrite output file without asking; -vn: no video; -acodec pcm_s16le: raw, uncompressed WAV
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        output_wav_path
    ], check=True, capture_output=True)

def insert_audio_ffmpeg(video_path, audio_path, output_video_path):
    """Re-inserts the watermarked audio into the original video."""
    # -c:v copy: copy video stream without re-encoding
    # -map 0:v:0: take video stream from first input (0)
    # -map 1:a:0: take audio stream from second input (1)
    # -shortest: finish encoding when the shortest input stream ends
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        output_video_path
    ], check=True, capture_output=True)

# --- Core Processing Logic ---

# Use Streamlit's cache to prevent re-processing the same file unnecessarily
# The hash will be based on the video file content and the user_id (watermark)
@st.cache_data
def process_video_to_bytes(video_path, user_id):
    """
    Processes the video and returns the processed video content as bytes.
    This fixes the issue where the temporary file was deleted before download.
    """
    st.info(f"Processing video for user ID: {user_id}...")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_audio_wav = os.path.join(temp_dir, "temp_audio.wav")
        watermarked_audio_wav = os.path.join(temp_dir, "watermarked_audio.wav")
        watermarked_audio_mp3 = os.path.join(temp_dir, "watermarked_audio.mp3")
        processed_video_path = os.path.join(temp_dir, "processed_video.mp4")

        try:
            # 1. Extract audio
            extract_audio_ffmpeg(video_path, temp_audio_wav)

            # 2. Embed watermark into WAV
            embed_watermark(temp_audio_wav, str(user_id), watermarked_audio_wav)

            # 3. Convert watermarked WAV to MP3 (FFmpeg might handle MP3 better)
            sound = AudioSegment.from_wav(watermarked_audio_wav)
            sound.export(watermarked_audio_mp3, format="mp3")

            # 4. Re-insert audio into video
            insert_audio_ffmpeg(video_path, watermarked_audio_mp3, processed_video_path)

            # 5. Read the final video into memory (bytes) before the temp directory is wiped
            with open(processed_video_path, "rb") as f:
                video_bytes = f.read()
            
            st.success("Video processing complete!")
            return video_bytes
        
        except subprocess.CalledProcessError as e:
            st.error(f"FFmpeg command failed. Is FFmpeg installed? Error: {e.stderr.decode()}")
            return None
        except Exception as e:
            st.error(f"An error occurred during processing: {e}")
            return None

# --- Streamlit App ---

def main():
    st.title("Simple OTT Video App with Audio Watermarking")

    # Initialize Session State
    if 'users' not in st.session_state:
        st.session_state.users = {}
    if 'logged_in_user' not in st.session_state:
        st.session_state.logged_in_user = None

    # Sidebar for login/registration
    with st.sidebar:
        st.header("🔑 Authentication")
        if st.session_state.logged_in_user:
            st.write(f"Logged in as: **{st.session_state.logged_in_user}** (ID: {st.session_state.users[st.session_state.logged_in_user]['id']})")
            if st.button("Logout"):
                st.session_state.logged_in_user = None
                st.rerun() # Use st.rerun() for instant UI refresh on state change
        else:
            auth_mode = st.radio("Choose:", ["Login", "Register"], key="auth_mode")
            username = st.text_input("Username", key="username_input")
            password = st.text_input("Password", type="password", key="password_input")
            
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
                        st.rerun() # Use st.rerun() for instant UI refresh on state change
                    else:
                        st.error("Invalid credentials")

    if not st.session_state.logged_in_user:
        st.warning("Please log in to access the video features.")
        return

    # User is logged in
    user_id = st.session_state.users[st.session_state.logged_in_user]['id']

    # --- Upload Section ---
    st.header("⬆️ Upload Video (Admin Mockup)")
    uploaded_file = st.file_uploader("Choose a video file", type=list(ALLOWED_EXTENSIONS))
    
    # Store the filename in session state for easier listing/cleanup
    if uploaded_file:
        if st.button("Save Upload"):
            # Logic to handle deleting old files (as in your original code)
            for f in os.listdir(UPLOAD_FOLDER):
                os.remove(os.path.join(UPLOAD_FOLDER, f))

            # Save new video
            filename = uploaded_file.name
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.session_state.last_uploaded_video = filename
            st.success(f"Uploaded and saved **{filename}**")
            st.rerun()

    # --- List and Download Videos ---
    st.header("🎬 Available Videos for Download")
    videos = [f for f in os.listdir(UPLOAD_FOLDER) if f.split('.')[-1].lower() in ALLOWED_EXTENSIONS]

    if videos:
        for video in videos:
            video_path = os.path.join(UPLOAD_FOLDER, video)
            
            # Use columns for layout
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{video}**")

            with col2:
                # 💡 Crucial Fix: Use st.download_button directly with a function 
                # that processes the data, or use session state if processing is slow 
                # and you need to show status updates.
                
                # Use a unique key for each button
                download_key = f"download_{video}_{user_id}"

                if st.button(f"Process & Get '{video}'", key=f"process_btn_{video}"):
                    # Run the processing function
                    video_bytes = process_video_to_bytes(video_path, user_id)
                    
                    if video_bytes:
                        # Store the processed bytes in session state for the download button
                        st.session_state[download_key] = video_bytes
                        st.success(f"Processing complete. Ready for download: watermarked_{video}")
                    else:
                        st.error("Failed to process video. See error details above.")

                if download_key in st.session_state:
                    st.download_button(
                        label="Download Processed Video",
                        data=st.session_state[download_key],
                        file_name=f"watermarked_{video}",
                        mime="video/mp4",
                        key=f"final_download_{video}"
                    )
                    # Optional: Clean up the session state after the download button appears
                    # You might need to manage this carefully depending on expected user flow.
                    # del st.session_state[download_key] 
    else:
        st.info("No videos uploaded yet.")

if __name__ == "__main__":
    main()
