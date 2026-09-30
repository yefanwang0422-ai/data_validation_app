"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Chip from "@mui/material/Chip";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { getRunSummary, RunSummary } from "@/lib/api";

export default function RunHistoryPage() {
  const { projectId, runIds, runId, setRunId } = useProject();
  const [summary, setSummary] = React.useState<RunSummary | null>(null);

  React.useEffect(() => {
    if (runId) {
      getRunSummary(projectId, runId).then(setSummary).catch(() => setSummary(null));
    }
  }, [projectId, runId]);

  return (
    <Box>
      <PageHeader title="Run Status & History" subtitle={`${runIds.length} run(s) found for project "${projectId}"`} />
      <Box sx={{ display: "flex", gap: 3 }}>
        <Card sx={{ minWidth: 320 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
              Runs (most recent first)
            </Typography>
            <List dense>
              {runIds.map((id) => (
                <ListItemButton key={id} selected={id === runId} onClick={() => setRunId(id)}>
                  <ListItemText primary={id.replace("run_", "")} />
                </ListItemButton>
              ))}
            </List>
          </CardContent>
        </Card>
        <Card sx={{ flexGrow: 1 }}>
          <CardContent>
            <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 600 }}>
              Run Summary
            </Typography>
            {summary ? (
              <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", mb: 2 }}>
                <Chip label={`Issues: ${summary.issue_count}`} color="warning" />
                <Chip label={`Review Items: ${summary.review_queue_count}`} color="info" />
                <Chip
                  label={`Cross-Ref Exceptions: ${summary.cross_reference_exception_count}`}
                  color="error"
                />
                <Chip label={`Source: ${summary.extraction_source || "sample"}`} color="primary" />
              </Box>
            ) : (
              <Typography color="text.secondary">Select a run to see its summary.</Typography>
            )}
            <pre style={{ fontSize: 12, background: "#F4F7FB", padding: 12, borderRadius: 8, overflowX: "auto" }}>
              {summary ? JSON.stringify(summary, null, 2) : ""}
            </pre>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
