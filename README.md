# 📧 Cold Mail Generator

Cold email generator for services company using groq, langchain and streamlit. It allows users to input the URL of a company's careers page. The tool then extracts job listings from that page and generates personalized cold emails. These emails include relevant portfolio links sourced from a vector database, based on the specific job descriptions.

**Imagine a scenario:**

- Rakuten needs a Principal Software Engineer and is spending time and resources in the hiring process, on boarding, training etc
- Norul is Software Development company can provide a dedicated software development engineer to Nike. So, the business development executive (Jewel) from Norul is going to reach out to Rakuten via a cold email.

![img.png](imgs/img.png)

## Architecture Diagram

![img.png](imgs/architecture.png)

## Set-up

1. To get started we first need to get an API_KEY from here: https://console.groq.com/keys. Inside `app/.env` update the value of `GROQ_API_KEY` with the API_KEY you created.

2. To get started, first install the dependencies using:
   ```commandline
    pip install -r requirements.txt
   ```
3. Run the streamlit app:

   ```commandline
   streamlit run app/main.py

   ```

## Powershell activate and deactivate

```
  deactivate
venv\Scripts\activate

```
How It Now Works:

URL Analysis: Automatically extracts company name from job board URLs
Job Extraction: Gets actual job title, skills, and requirements
Auto-Update: Updates the role input field with the actual job title
Skill Matching: Maps required skills to your portfolio techstack
Dynamic Email: Generates personalized emails using actual job data
Multiple Jobs: Handles multiple job postings with different personalized emails



The system will now:

Auto-detect "Zeals" as the company name
Extract the actual job role (e.g., "AI・機械学習エンジニア")
Use this role throughout the email instead of the default "AI/ML Engineer"
Reference the specific skills mentioned in the job posting
Create a truly personalized email for that specific role



Copyright (C) Norul. All rights reserved.

**Additional Terms:**
Do not use without permission
