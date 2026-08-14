import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service · Pulsai 3D",
  description: "Terms for using the Pulsai 3D web application.",
};

export default function TermsPage() {
  return (
    <main style={pageStyle}>
      <article style={cardStyle}>
        <p style={eyebrowStyle}>PULSAI 3D</p>
        <h1>Terms of Service</h1>
        <p><strong>Effective date:</strong> 14 August 2026</p>

        <h2>Prototype service</h2>
        <p>
          Pulsai 3D helps create and edit CAD and mesh files and prepare them for 3D printing. The
          service is provided as an evolving prototype without a guarantee that every prompt, imported
          model, generated part, export, or print will succeed.
        </p>

        <h2>Engineering and print safety</h2>
        <p>
          Automated geometry, manufacturability checks, orientation, slicing estimates, and motion
          previews are aids, not professional engineering certification. You are responsible for
          checking dimensions, tolerances, material, printer settings, toolpaths, loads, clearances,
          and safe use before manufacturing. Do not rely on the service for safety-critical parts.
        </p>

        <h2>Your content and accounts</h2>
        <p>
          You retain rights in content you submit and must have permission to use it. You authorize the
          service and its infrastructure and model providers to process that content to provide the
          requested features. Keep your Google account and provider API keys secure; do not share keys
          through prompts, project names, or uploaded files.
        </p>

        <h2>Acceptable use and costs</h2>
        <p>
          Do not misuse the service, bypass access controls or quotas, interfere with other users, or
          use it unlawfully. When you use your own provider key, charges are billed by that provider to
          your account under its pricing and terms. Platform-funded model usage is unavailable unless
          Pulsai 3D explicitly enables it.
        </p>

        <h2>Open-source software</h2>
        <p>
          The source code is offered under the GNU Affero General Public License v3.0 or later. That
          software license governs copying, modification, and distribution of the code; these service
          terms govern use of the hosted Pulsai 3D instance.
        </p>

        <h2>Availability and changes</h2>
        <p>
          Features may change, fail, or be withdrawn, and external providers may be unavailable. To
          the extent permitted by law, the service is provided without warranties and liability is
          limited to the maximum extent permitted by applicable law.
        </p>

        <h2>Contact</h2>
        <p>Questions may be sent to <a href="mailto:gizmuf@gmail.com">gizmuf@gmail.com</a>.</p>

        <p style={footerStyle}><Link href="/">Back to Pulsai 3D</Link> · <Link href="/privacy">Privacy Policy</Link></p>
      </article>
    </main>
  );
}

const pageStyle = { minHeight: "100vh", padding: "48px 20px", background: "#f4f0e8" };
const cardStyle = { maxWidth: 780, margin: "0 auto", padding: "clamp(28px, 6vw, 64px)", background: "#fff", border: "1px solid rgba(35,35,35,.12)", borderRadius: 24, lineHeight: 1.7 };
const eyebrowStyle = { fontSize: 12, letterSpacing: ".18em", opacity: .58 };
const footerStyle = { marginTop: 40, paddingTop: 20, borderTop: "1px solid rgba(35,35,35,.12)" };
