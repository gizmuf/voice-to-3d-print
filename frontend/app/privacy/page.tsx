import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy · Pulsai 3D",
  description: "Privacy information for the Pulsai 3D web application.",
};

export default function PrivacyPage() {
  return (
    <main style={pageStyle}>
      <article style={cardStyle}>
        <p style={eyebrowStyle}>PULSAI 3D</p>
        <h1>Privacy Policy</h1>
        <p><strong>Effective date:</strong> 14 August 2026</p>

        <h2>What we process</h2>
        <p>
          When you sign in with Google, Pulsai 3D receives your Google account identifier and may
          receive your verified email address and display name. We use the identifier to keep your
          projects, revisions, conversations, and generated CAD and print artifacts separate from
          other users.
        </p>

        <h2>Project and service data</h2>
        <p>
          Prompts, uploaded reference files, generated geometry, previews, revisions, slicing output,
          and operational logs may be stored so the service can build, restore, diagnose, and export
          your project. Data is hosted using Google Cloud services. Requests that use an external AI
          provider are also processed under that provider&apos;s terms and privacy policy.
        </p>

        <h2>Your provider API keys</h2>
        <p>
          If you provide Anthropic, OpenAI, Gemini, Meshy, or Tripo API keys, the web app keeps them
          in browser memory and sends only the key needed for the requested task to the backend over
          HTTPS. Pulsai 3D is designed not to persist those keys in account or project records,
          browser storage, or logs. Closing or reloading the page clears them from browser memory.
        </p>

        <h2>Sharing and retention</h2>
        <p>
          We do not sell personal data. We share data only with infrastructure and model providers
          needed to operate the requested feature, or when required by law. Project data and backups
          may remain until deletion is requested and applicable operational retention periods expire.
        </p>

        <h2>Your choices</h2>
        <p>
          You may stop using the service at any time and request access to or deletion of your account
          and project data. Do not upload confidential or third-party material unless you are entitled
          to process it.
        </p>

        <h2>Contact</h2>
        <p>
          For privacy questions or deletion requests, contact{" "}
          <a href="mailto:gizmuf@gmail.com">gizmuf@gmail.com</a>.
        </p>

        <p style={footerStyle}><Link href="/">Back to Pulsai 3D</Link> · <Link href="/terms">Terms of Service</Link></p>
      </article>
    </main>
  );
}

const pageStyle = { minHeight: "100vh", padding: "48px 20px", background: "#f4f0e8" };
const cardStyle = { maxWidth: 780, margin: "0 auto", padding: "clamp(28px, 6vw, 64px)", background: "#fff", border: "1px solid rgba(35,35,35,.12)", borderRadius: 24, lineHeight: 1.7 };
const eyebrowStyle = { fontSize: 12, letterSpacing: ".18em", opacity: .58 };
const footerStyle = { marginTop: 40, paddingTop: 20, borderTop: "1px solid rgba(35,35,35,.12)" };
