import type { Metadata } from "next";
import ThemeRegistry from "@/theme/ThemeRegistry";
import { ProjectProvider } from "@/components/ProjectContext";
import AppShell from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Supply Chain Design_Data Validation",
  description: "Supply chain data cleaning, validation, and modeling-readiness platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0 }}>
        <ThemeRegistry>
          <ProjectProvider>
            <AppShell>{children}</AppShell>
          </ProjectProvider>
        </ThemeRegistry>
      </body>
    </html>
  );
}
