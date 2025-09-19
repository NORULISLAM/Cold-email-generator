import os

from dotenv import load_dotenv
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
from pydantic import SecretStr

load_dotenv()


class Chain:

    def __init__(self):
        self.llm = ChatGroq(temperature=0, groq_api_key=os.getenv("GROQ_API_KEY"), model_name="llama-3.3-70b-versatile")

    def extract_jobs(self, cleaned_text):
        prompt_extract = PromptTemplate.from_template(
            """
            ### SCRAPED TEXT FROM WEBSITE:
            {page_data}
            ### INSTRUCTION:
            The scraped text is from the career's page of a website.
            Your job is to extract the job postings and return them in JSON format containing the following keys: `role`, `experience`, `skills` and `description`.
            Only return the valid JSON.
            ### VALID JSON (NO PREAMBLE):
            """
        )
        chain_extract = prompt_extract | self.llm
        res = chain_extract.invoke(input={"page_data": cleaned_text})
        try:
            json_parser = JsonOutputParser()
            res = json_parser.parse(res.content)
        except OutputParserException:
            raise OutputParserException("Context too big. Unable to parse jobs.")
        return res if isinstance(res, list) else [res]

    def write_mail(self, job_description, company_name, recipient_name, role_title, techstack_list,
                   extracted_job_data=None):
        """
        Enhanced email generation with dynamic content based on actual job data
        """

        # Extract key information from the job data
        actual_role = extracted_job_data.get('role', role_title) if extracted_job_data else role_title
        required_skills = extracted_job_data.get('skills', []) if extracted_job_data else []
        experience_level = extracted_job_data.get('experience',
                                                  'Not specified') if extracted_job_data else 'Not specified'
        job_desc_summary = extracted_job_data.get('description',
                                                  'Not available') if extracted_job_data else job_description

        # Create dynamic skill matching
        skill_matches = self._match_skills_to_portfolio(required_skills, techstack_list)

        prompt_email = PromptTemplate.from_template(
            """
            ### INSTRUCTION:
            You are an expert AI-powered career strategist. Compose a concise, high-impact cold email on behalf of Norul Islam (AI/ML Engineer). 
            Write as Norul in a professional, confident tone that directly addresses the specific job requirements.

            ### JOB-SPECIFIC INFORMATION:
            Company Name: {company_name}
            Recipient: {recipient_name}
            Actual Job Role: {actual_role}
            Required Skills: {required_skills}
            Experience Level: {experience_level}
            Job Description Summary: {job_desc_summary}

            ### PORTFOLIO MATCHES:
            {skill_matches}

            ### CANDIDATE PROFILE:
            Core Competency: AI/ML Engineering with full-stack & microservices strength. A builder who ideates and deploys.

            Key Portfolio Assets:
            - Multi-Agent / Agentic AI System (Planner, Architect, Coder agents generate web apps from one natural-language prompt)
              Live Demo: https://huggingface.co/spaces/Jewelr16/Create_new_project
            - AI Cold Email Generator (auto response from JD)
              Live Demo: https://huggingface.co/spaces/Norul-islam/COLD-EMAIL-GENERATOR
            - Document summary App 
              Live Demo: https://money-forward-app.vercel.app/
            - Full-Stack Microservices Project (scalable, resilient, decoupled)
              GitHub: https://github.com/NORULISLAM/Micro-services
            - Professional Web Development & Deployment
              Corporate Site: https://yotsuba-system.co.jp/

            ### EXECUTION REQUIREMENTS:
            1. Analyze the ACTUAL job requirements from the extracted data
            2. Map the TOP 3 most critical requirements to specific portfolio projects
            3. Use the ACTUAL role title: "{actual_role}" throughout the email
            4. Reference specific required skills: {required_skills}
            5. Keep email concise: 150-220 words per language
            6. Make it feel personalized to this specific job posting

            ### OUTPUT FORMAT:
            Generate both Japanese and English versions with the ACTUAL job role and requirements.

            --- JAPANESE VERSION ---
            件名: 貴社の{actual_role}募集への具体的提案：即戦力として貢献可能

            {recipient_name} 様

            {company_name} の「{actual_role}」に強い関心を持ち、即戦力として貢献できると確信しております。要点は以下の3点です。

            【要件適合（上位3点）】
            [Analyze the actual required skills: {required_skills} and map to portfolio]
            1) [First major requirement]: 私の「Multi-Agent/Agentic AI（Planner/Architect/Coder）」の実装で、自然言語から自律的にWebアプリを生成。要件の根拠をライブで提示可能。
            2) [Second major requirement]: Microservicesプロジェクトでスケーラブルな分散設計・観点を実装（耐障害性・独立デプロイ・疎結合）。
            3) [Third major requirement]: フロント～インフラまで一気通貫（YSDコーポレートサイト構築・運用）、実務での品質・納期・継続改善。

            【実績（ライブ）】
            - 自律エージェント生成デモ：https://huggingface.co/spaces/Jewelr16/Create_new_project
            - 自動メール応答（JD駆動）：https://huggingface.co/spaces/Norul-islam/COLD-EMAIL-GENERATOR
            - 金融系フロント：https://money-forward-app.vercel.app/
            - Microservices（コード）：https://github.com/NORULISLAM/Micro-services

            最短15分でお打ち合わせの機会を頂ければ、要件と成果物の直結イメージを具体的にご説明いたします。ご検討を何卒よろしくお願い申し上げます。

            何卒よろしくお願い申し上げます。
            Norul Islam
            GitHub: https://github.com/NORULISLAM

            --- ENGLISH VERSION ---
            Subject: Proposal for {company_name}'s {actual_role}: Direct skill-to-deliverable match

            Dear {recipient_name},

            I'm excited to apply for {company_name}'s "{actual_role}" position. Based on your specific requirements, I can contribute immediately:

            [Top 3 Requirement Matches for {actual_role}]
            [Map these specific skills to portfolio: {required_skills}]
            1) [First key requirement]: My Multi-Agent/Agentic AI system (Planner/Architect/Coder) demonstrates autonomous development capabilities—turning natural language into working applications.
            2) [Second key requirement]: Microservices project shows scalable, fault-tolerant architecture with independent deployability.
            3) [Third key requirement]: Full-stack delivery experience from frontend to infrastructure, proven with corporate site development and maintenance.

            [Live Proof]
            - Agentic AI demo: https://huggingface.co/spaces/Jewelr16/Create_new_project
            - JD-driven auto emailer: https://huggingface.co/spaces/Norul-islam/COLD-EMAIL-GENERATOR
            - Document summary App: https://money-forward-app.vercel.app/
            - Microservices code: https://github.com/NORULISLAM/Micro-services

            May we schedule a 15-minute call? I'll demonstrate how my specific experience aligns with your {actual_role} requirements and show concrete deliverables.

            Best regards,
            Norul Islam
            GitHub: https://github.com/NORULISLAM

            ### IMPORTANT: 
            - Replace [brackets] with actual analysis of the job requirements
            - Use the actual role title "{actual_role}" consistently
            - Reference the specific skills: {required_skills}
            - Make this feel customized to this exact job posting
            """
        )

        chain_email = prompt_email | self.llm
        res = chain_email.invoke({
            "company_name": company_name,
            "recipient_name": recipient_name,
            "actual_role": actual_role,
            "required_skills": ', '.join(required_skills) if required_skills else 'Not specified',
            "experience_level": experience_level,
            "job_desc_summary": job_desc_summary[:500] + "..." if len(job_desc_summary) > 500 else job_desc_summary,
            "skill_matches": skill_matches
        })
        return res.content

    def _match_skills_to_portfolio(self, required_skills, techstack_list):
        """
        Create a mapping between required skills and portfolio techstack
        """
        if not required_skills or not techstack_list:
            return "No specific skill matches found in portfolio."

        matches = []
        for skill in required_skills:
            skill_lower = skill.lower()
            for tech in techstack_list:
                if skill_lower in tech.lower() or tech.lower() in skill_lower:
                    matches.append(f"- {skill} → Portfolio experience: {tech}")
                    break

        if matches:
            return "SKILL MATCHING:\n" + "\n".join(matches)
        else:
            return f"Portfolio techstack available: {', '.join(techstack_list[:5])}"


if __name__ == "__main__":
    print(os.getenv("GROQ_API_KEY"))