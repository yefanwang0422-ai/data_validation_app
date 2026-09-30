"use client";

import * as React from "react";
import { getSqlStatus, listRuns } from "@/lib/api";

interface ProjectContextValue {
  projectId: string;
  setProjectId: (id: string) => void;
  runId: string | null;
  setRunId: (id: string | null) => void;
  runIds: string[];
  refreshRuns: () => Promise<void>;
  sqlConfigured: boolean;
  refreshSqlStatus: () => Promise<void>;
}

const ProjectContext = React.createContext<ProjectContextValue | undefined>(undefined);

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const [projectId, setProjectId] = React.useState<string>("demo_project");
  const [runId, setRunId] = React.useState<string | null>(null);
  const [runIds, setRunIds] = React.useState<string[]>([]);
  const [sqlConfigured, setSqlConfigured] = React.useState<boolean>(false);

  const refreshRuns = React.useCallback(async () => {
    try {
      const runs = await listRuns(projectId);
      setRunIds(runs);
      if (runs.length > 0 && !runId) {
        setRunId(runs[0]);
      }
    } catch {
      setRunIds([]);
    }
  }, [projectId, runId]);

  React.useEffect(() => {
    refreshRuns();
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshSqlStatus = React.useCallback(async () => {
    try {
      const configured = await getSqlStatus();
      setSqlConfigured(configured);
    } catch {
      setSqlConfigured(false);
    }
  }, []);

  React.useEffect(() => {
    refreshSqlStatus();
  }, [refreshSqlStatus]);

  return (
    <ProjectContext.Provider
      value={{
        projectId,
        setProjectId,
        runId,
        setRunId,
        runIds,
        refreshRuns,
        sqlConfigured,
        refreshSqlStatus,
      }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  const ctx = React.useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used within a ProjectProvider");
  return ctx;
}
