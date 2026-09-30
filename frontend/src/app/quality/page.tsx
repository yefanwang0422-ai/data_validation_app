"use client";

import * as React from "react";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import LinearProgress from "@mui/material/LinearProgress";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { getDatasetQuality, DatasetQuality } from "@/lib/api";

export default function DatasetQualityPage() {
  const { projectId, runId } = useProject();
  const [quality, setQuality] = React.useState<Record<string, DatasetQuality>>({});

  React.useEffect(() => {
    if (runId) {
      getDatasetQuality(projectId, runId).then(setQuality).catch(() => setQuality({}));
    }
  }, [projectId, runId]);

  return (
    <Box>
      <PageHeader title="Dataset Quality Dashboard" subtitle="Validation status breakdown across all 8 datasets" />
      <Grid container spacing={2}>
        {Object.values(quality).map((q) => (
          <Grid item xs={12} sm={6} md={3} key={q.dataset}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                  {q.dataset.replace(/_/g, " ")}
                </Typography>
                <Typography variant="h4" sx={{ color: "primary.main", fontWeight: 700 }}>
                  {q.pct_valid}%
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Valid ({q.row_count} rows)
                </Typography>
                <LinearProgress
                  variant="determinate"
                  value={q.pct_valid}
                  sx={{
                    mt: 1.5,
                    mb: 1,
                    height: 8,
                    borderRadius: 4,
                    bgcolor: "#E3E9F5",
                    "& .MuiLinearProgress-bar": { bgcolor: "#0B3D91" },
                  }}
                />
                <Typography variant="caption" color="text.secondary" display="block">
                  Review: {q.pct_needs_review}% · Invalid: {q.pct_invalid}%
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block">
                  AI-filled: {q.ai_filled_count}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
