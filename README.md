# SASAA – AI Voice Note Guardian

**An AI-powered voice note verification and protection platform**

SASAA (Smart Audio Security and Analysis) is an intelligent voice note guardian designed to transform voice messages into structured, verified, and actionable information.

The application uses **Gnani AI Speech-to-Text technology** to convert voice recordings into text and applies intelligent processing to identify important information, extract entities, and help users verify the accuracy of voice-based instructions.

The primary goal is to reduce misunderstandings, prevent errors, and improve trust in voice communication.

---

## 🚀 Project Overview

Voice messages are widely used for sharing important information such as names, phone numbers, dates, meeting schedules, payment amounts, and instructions.

However, manually listening to recordings multiple times can be time-consuming and may lead to mistakes.

SASAA addresses this challenge by providing an intelligent platform that:

- Converts voice recordings into text.
- Extracts important information from transcripts.
- Identifies critical entities such as names, phone numbers, dates, times, and amounts.
- Helps users review and verify extracted information.
- Maintains original transcripts separately from edited versions.
- Provides a centralized interface for managing voice notes.

---

## ✨ Key Features

### 1. AI-Powered Speech Recognition
- Integrates Gnani AI Speech-to-Text technology.
- Converts audio recordings into readable text.
- Helps users understand voice messages without repeatedly listening.

### 2. Intelligent Entity Extraction
- Identifies important information from transcripts.
- Extracts names, phone numbers, dates, times, and monetary values.
- Organizes extracted information for easier verification.

### 3. Voice Note Verification
- Helps users review extracted information.
- Displays verification results and risk indicators.
- Makes it easier to identify information that requires attention.

### 4. Transcript Management
- Preserves original transcripts.
- Supports user-edited transcript versions.
- Maintains a separation between original and modified information.

### 5. User Authentication
- Provides a login and registration interface.
- Uses token-based authentication.
- Protects access to user-specific application features.

### 6. Dashboard
- Provides a centralized interface.
- Displays voice note information and processing results.
- Improves the overall user experience.

---

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Frontend | React.js, JavaScript |
| Styling | CSS |
| Backend | Python |
| AI Speech Recognition | Gnani AI |
| API Communication | REST API |
| Authentication | Token-based authentication |
| Version Control | Git and GitHub |
| Development Tools | VS Code |

---

## 🧠 Gnani AI Integration

Gnani AI is an important technology component of SASAA.

The application uses Gnani AI Speech-to-Text capabilities to convert spoken audio into textual information.

**Processing workflow:**

1. User uploads or records a voice note.
2. Audio is processed using Gnani AI Speech-to-Text.
3. The generated transcript is received by the application.
4. The backend processes the transcript.
5. Important entities are extracted.
6. Verification results are generated.
7. Users can review the processed information through the frontend.

---

## 🏗️ System Architecture

```text
             USER
               |
               v
       REACT FRONTEND
               |
               v
         BACKEND API
               |
       +-------+-------+
       |               |
       v               v
   GNANI AI       ENTITY EXTRACTION
  SPEECH-TO-TEXT       |
       |               |
       v               v
    TRANSCRIPT    VERIFICATION
       |               |
       +-------+-------+
               |
               v
        DATABASE LAYER
               |
               v
       RESULTS & DASHBOARD
```

---

## 📂 Project Structure

The project is organized into frontend and backend components.

```text
SASAA/
│
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── ...
│
├── backend/
│   ├── app/
│   ├── requirements.txt
│   └── ...
│
├── .gitignore
└── README.md
```

*Note: Update this structure to match the actual folders and filenames in your repository.*

---

## ⚙️ Installation and Setup

### Prerequisites

Make sure you have installed:

- Python 3.10 or later
- Node.js and npm
- Git
- Visual Studio Code

### 1. Clone the Repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

```bash
cd VoiceNoteGuardian
```

### 2. Backend Setup

Navigate to the backend directory:

```bash
cd backend
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate the environment on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure the required environment variables in your `.env` file.

Start the backend using the actual entry point configured in your project.

### 3. Frontend Setup

Navigate to the frontend directory:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Start the development server using the configured npm development script:

```bash
npm run dev
```

Open the local development URL displayed in your terminal.

---

## 🔐 Environment Configuration

Create a `.env` file in the appropriate backend directory and configure the required credentials.

Example:

```env
GNANI_API_KEY=your_gnani_api_key
DATABASE_URL=your_database_url
SECRET_KEY=your_secret_key
```

**Important:** Never upload API keys, passwords, tokens, or other sensitive credentials to GitHub.

---

## 🔄 Application Workflow

```text
Voice Recording
      |
      v
Audio Processing
      |
      v
Gnani AI Speech-to-Text
      |
      v
Transcript Generation
      |
      v
Entity Extraction
      |
      v
Information Verification
      |
      v
Results Display
      |
      v
User Review
```

---

## 🎯 Project Objectives

- Improve the reliability of voice-based communication.
- Reduce errors caused by misinterpreted voice messages.
- Automate speech-to-text conversion.
- Extract meaningful information from unstructured audio.
- Provide an easy-to-use voice verification platform.
- Demonstrate the practical application of AI in everyday communication.

---

## 🔮 Future Enhancements

- Real-time voice note processing.
- Advanced AI-powered contextual verification.
- Multilingual speech recognition.
- Improved fraud and suspicious instruction detection.
- Voice note history and analytics.
- Enhanced security and privacy controls.

---

## 👩‍💻 Project Information

**Project Name:** SASAA – AI Voice Note Guardian

**Project Type:** AI-powered SaaS Application

**Organization:** Gnani AI Internship Project

**Domain:** Artificial Intelligence, Speech Recognition, Natural Language Processing, and Software Development

---

## 🙌 Acknowledgements

Special thanks to **Gnani AI** for the opportunity to explore and implement AI-powered speech technologies as part of this internship project.

This project represents an effort to combine speech recognition, intelligent information extraction, and software engineering to solve a real-world communication challenge.

---

**Built with innovation, AI, and a vision for safer voice communication.**