import asyncio
import smtplib
from urllib.parse import quote
from html import escape
from datetime import datetime
from email.message import EmailMessage
from app.config import Settings


class EmailService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def send_otp(self, email: str, otp: str, purpose: str) -> None:
        if not self.settings.email_enabled:
            return
        label = "account registration" if purpose == "CANDIDATE_REGISTRATION" else "password reset"
        message = EmailMessage()
        message["Subject"] = f"NovaTech verification code: {otp}"
        message["From"] = self.settings.email_from or self.settings.smtp_user
        message["To"] = email
        message.set_content(
            f"Your NovaTech {label} verification code is {otp}. "
            f"It expires in {self.settings.otp_expiry_minutes} minutes. "
            "Do not share this code with anyone."
        )
        await asyncio.to_thread(self._send, message)

    async def send_staff_invitation(self, email: str, full_name: str, role: str, token: str, expires_at: datetime) -> None:
        if not self.settings.email_enabled:
            return
        link = f"{self.settings.frontend_url.rstrip('/')}/invite?token={token}"
        message = EmailMessage()
        message["Subject"] = "You are invited to NovaTech Solutions"
        message["From"] = self.settings.email_from or self.settings.smtp_user
        message["To"] = email
        message.set_content(
            f"Hello {full_name},\n\nNovaTech Solutions invited you to join as {role.replace('_', ' ').title()}. "
            f"Complete setup before {expires_at.isoformat()} by visiting:\n{link}\n\n"
            "This invitation is single-use. If you did not expect it, contact your administrator."
        )
        await asyncio.to_thread(self._send, message)

    def _branded(self, title: str, greeting: str, paragraphs: list[str], button_url: str | None = None, button_label: str = "Open", actions: list[tuple[str, str]] | None = None) -> str:
        safe_paragraphs = [escape(value).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>") for value in paragraphs]
        body = "".join(f"<p style='margin:0 0 14px;color:#33443c;line-height:1.6'>{value}</p>" for value in safe_paragraphs)
        links = list(actions or [])
        if button_url:
            links.insert(0, (button_label, button_url))
        buttons = "".join(
            f"<a href='{escape(url, quote=True)}' style='display:inline-block;margin:0 10px 10px 0;background:{'#0d6b4d' if index == 0 else '#e9f3ee'};color:{'#fff' if index == 0 else '#0d6b4d'};text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:bold'>{escape(label)}</a>"
            for index, (label, url) in enumerate(links)
        )
        action_block = f"<p style='margin:24px 0'>{buttons}</p>" if buttons else ""
        return f"<html><body style='margin:0;background:#f4f6f4;font-family:Arial,sans-serif'><div style='max-width:640px;margin:28px auto;background:#fff;border:1px solid #dbe2dc;border-radius:14px;overflow:hidden'><div style='background:#12211b;color:#fff;padding:24px 30px'><b style='font-size:20px'>NovaTech Solutions</b></div><div style='padding:30px'><h1 style='font-size:24px;color:#12211b;margin:0 0 20px'>{escape(title)}</h1><p style='color:#12211b'>Hello {escape(greeting)},</p>{body}{action_block}<p style='margin-top:28px;color:#718078;font-size:13px'>NovaTech Solutions Recruitment Team</p></div></div></body></html>"

    async def send_application_received(self, email: str, name: str, position: str, application_code: str) -> bool:
        if not self.settings.email_enabled:
            return False
        paragraphs = [
            f"Your application for <b>{position}</b> was successfully received.",
            f"Application reference: <b>{application_code}</b>",
            "Our hiring team will review your CV and contact you by email when your application status changes.",
            "Please keep your application reference for future communication.",
        ]
        message = EmailMessage()
        message["Subject"] = f"Application received - {position} | NovaTech Solutions"
        message["From"] = self.settings.email_from or self.settings.smtp_user
        message["To"] = email
        message.set_content(
            f"Hello {name},\n\nYour application for {position} was successfully received.\n"
            f"Application reference: {application_code}\n\n"
            "Our hiring team will contact you when your application status changes."
        )
        message.add_alternative(self._branded("Application successfully received", name, paragraphs), subtype="html")
        await asyncio.to_thread(self._send, message)
        return True

    async def send_application_status(self, email: str, name: str, position: str, status: str) -> bool:
        if not self.settings.email_enabled:
            return False
        content = {
            "SHORTLISTED": ("You have been shortlisted", [f"Your application for <b>{position}</b> has been shortlisted.", "Our hiring team will assign an interviewer and send the confirmed schedule and Google Meet link separately."]),
            "MANUAL_REVIEW": ("Your application is under review", [f"Your application for <b>{position}</b> is being reviewed by our hiring team.", "No final decision has been made. We will contact you when the review is complete."]),
            "REJECTED": ("Application update", [f"Thank you for applying for <b>{position}</b>.", "After review, we will not be progressing this application. We appreciate your interest in NovaTech Solutions."]),
            "SELECTED": ("You have been selected", [f"Congratulations—our hiring team selected you for <b>{position}</b>.", "HR is preparing your formal offer. You will receive a separate secure offer notification when it is ready."]),
            "INTERVIEWED": ("Interview completed", [f"Your interview for <b>{position}</b> has been completed.", "The hiring manager and HR are reviewing the interview scorecard. No final decision has been made yet."]),
        }.get(status)
        if not content:
            return False
        message = EmailMessage(); message["Subject"] = f"NovaTech - {content[0]}"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = email
        message.set_content("\n\n".join([f"Hello {name}"] + [p.replace("<b>", "").replace("</b>", "") for p in content[1]]))
        message.add_alternative(self._branded(content[0], name, content[1]), subtype="html")
        await asyncio.to_thread(self._send, message)
        return True

    async def send_employee_activation(self, email: str, name: str, title: str, level: str, department: str) -> None:
        if not self.settings.email_enabled:
            return
        link = f"{self.settings.frontend_url.rstrip('/')}/candidate-register?email={quote(email, safe='')}"
        paragraphs = [f"Your offer for <b>{title}</b> has been accepted.", f"Employment level: <b>{level}</b>", f"Department: <b>{department}</b>", "Use the secure link below to create or confirm your account credentials and open your onboarding workspace."]
        message = EmailMessage(); message["Subject"] = f"NovaTech - Complete your employee account - {title}"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = email
        message.set_content(f"Hello {name},\n\nComplete your employee account: {link}")
        message.add_alternative(self._branded("Welcome to NovaTech", name, paragraphs, link, "Set up employee account"), subtype="html")
        await asyncio.to_thread(self._send, message)

    async def send_offer_ready(self, email: str, name: str, title: str, expiry: str, offer_id: str, response_token: str) -> bool:
        if not self.settings.email_enabled:
            return False
        if not all((self.settings.smtp_host, self.settings.smtp_user, self.settings.smtp_password)):
            return False
        if not email or "@" not in email:
            return False
        link = f"{self.settings.frontend_url.rstrip('/')}/offer?offer_id={quote(offer_id, safe='')}&token={quote(response_token, safe='')}"
        paragraphs = [f"Your formal offer for <b>{title}</b> is ready.", f"Please review and respond before <b>{expiry}</b>.", "Use the secure single-use response link below. Your employee account invitation will be sent only after you accept."]
        message = EmailMessage(); message["Subject"] = f"NovaTech - Your offer for {title}"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = email
        message.set_content(f"Hello {name},\n\nYour offer for {title} is ready. Review and respond here: {link}\nExpiry: {expiry}")
        message.add_alternative(self._branded("Your employment offer", name, paragraphs, link, "Review offer"), subtype="html")
        await asyncio.to_thread(self._send, message)
        return True

    async def send_interview_assignment_notice(self, candidate_email: str, candidate_name: str, position: str) -> None:
        if not self.settings.email_enabled:
            return
        message = EmailMessage(); message["Subject"] = f"Interviewer assigned - {position}"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = candidate_email
        paragraphs = [f"An interviewer has been assigned to your <b>{position}</b> application.", "The interviewer will select an available date and time. You will receive a second email containing the confirmed schedule and Google Meet link."]
        message.set_content(f"Hello {candidate_name},\n\nAn interviewer has been assigned. Schedule details will follow.")
        message.add_alternative(self._branded("Your interview is being arranged", candidate_name, paragraphs), subtype="html")
        await asyncio.to_thread(self._send, message)

    async def send_candidate_registration(self, email: str, name: str, position: str) -> None:
        if not self.settings.email_enabled:
            return
        link = f"{self.settings.frontend_url.rstrip('/')}/candidate-register?email={quote(email, safe='')}"
        paragraphs = [f"Your <b>{position}</b> application has progressed to the hiring process.", "Create your secure candidate account using the same email address that you used in your application. You will verify a one-time code and choose your own username and password.", "Your portal will show application status, interview schedule, Google Meet access, offers and onboarding updates."]
        message = EmailMessage(); message["Subject"] = "Create your NovaTech candidate account"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = email
        message.set_content(f"Hello {name},\n\nCreate your candidate account: {link}\nUse this email address: {email}")
        message.add_alternative(self._branded("Create your candidate account", name, paragraphs, link, "Create secure account"), subtype="html")
        await asyncio.to_thread(self._send, message)

    async def send_interview_schedule(self, *, email: str, name: str, position: str, interviewer: str, start: str, end: str, meet_url: str, interview_code: str, confirmation_token: str | None = None, reminder: bool = False) -> None:
        if not self.settings.email_enabled:
            return
        title = "Interview reminder" if reminder else "Your interview is scheduled"
        paragraphs = [f"Position: <b>{position}</b>", f"Interviewer: <b>{interviewer}</b>", f"Start: <b>{start}</b>", f"End: <b>{end}</b>", f"Interview code: <b>{interview_code}</b>", "Join from a quiet place 5–10 minutes early and check your camera, microphone and internet connection.", "Google Meet does not normally use a separate password; access is provided through the secure meeting link."]
        actions = [("Join Google Meet", meet_url)]
        response_text = ""
        if confirmation_token:
            token = quote(confirmation_token, safe="")
            base = f"{self.settings.frontend_url.rstrip('/')}/interview?token={token}"
            confirm_url = f"{base}&action=CONFIRMED"
            reschedule_url = f"{base}&action=RESCHEDULE"
            actions = [("Confirm interview", confirm_url), ("Request another time", reschedule_url), ("Join Google Meet", meet_url)]
            paragraphs.append("Please confirm the time or request another time before the interview starts.")
            response_text = f"\nConfirm: {confirm_url}\nRequest another time: {reschedule_url}"
        message = EmailMessage(); message["Subject"] = f"NovaTech - {title} - {position}"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = email
        message.set_content(f"Hello {name},\n\n{title}\nPosition: {position}\nInterviewer: {interviewer}\nStart: {start}\nEnd: {end}\nJoin: {meet_url}\nInterview code: {interview_code}{response_text}\n\nPlease join 5–10 minutes early.")
        message.add_alternative(self._branded(title, name, paragraphs, actions=actions), subtype="html")
        await asyncio.to_thread(self._send, message)

    async def send_interview_response(self, *, email: str, name: str, position: str, action: str, requested_start: str | None = None) -> None:
        if not self.settings.email_enabled:
            return
        if action == "CONFIRMED":
            title = "Interview confirmed"
            paragraphs = [f"Your interview for <b>{position}</b> is confirmed.", "The schedule and Google Meet link remain available in your candidate portal and invitation email."]
        else:
            title = "Reschedule request received"
            paragraphs = [f"We received your request to reschedule the <b>{position}</b> interview.", f"Preferred time: <b>{requested_start or 'Not provided'}</b>", "HR or the hiring manager will review the request and send a revised invitation."]
        message = EmailMessage(); message["Subject"] = f"NovaTech - {title} - {position}"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = email
        message.set_content("\n\n".join([f"Hello {name}"] + [paragraph.replace("<b>", "").replace("</b>", "") for paragraph in paragraphs]))
        message.add_alternative(self._branded(title, name, paragraphs), subtype="html")
        await asyncio.to_thread(self._send, message)

    async def send_reschedule_decision(self, *, email: str, name: str, position: str, accepted: bool, reason: str = "") -> None:
        if not self.settings.email_enabled:
            return
        if accepted:
            title = "New interview time approved"
            paragraphs = [f"Your requested time for the <b>{position}</b> interview has been approved.", "A revised calendar invitation and schedule email have been sent with the exact time and Google Meet link.", "Please use the confirmation button in that email to confirm the new time."]
        else:
            title = "Interview time request update"
            paragraphs = [f"Your request to change the <b>{position}</b> interview time could not be approved.", f"Reason: <b>{reason or 'The assigned interviewer is unavailable at the requested time.'}</b>", "Your original interview schedule remains active. Contact the recruitment team if you need further assistance."]
        message = EmailMessage(); message["Subject"] = f"NovaTech - {title} - {position}"; message["From"] = self.settings.email_from or self.settings.smtp_user; message["To"] = email
        message.set_content("\n\n".join([f"Hello {name}"] + [paragraph.replace("<b>", "").replace("</b>", "") for paragraph in paragraphs]))
        message.add_alternative(self._branded(title, name, paragraphs), subtype="html")
        await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(self.settings.smtp_user, self.settings.smtp_password)
            refused = server.send_message(message)
            if refused:
                raise RuntimeError("SMTP server refused one or more recipients")
