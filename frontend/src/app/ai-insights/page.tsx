"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import Box from "@mui/material/Box";
import Grid from "@mui/material/Grid";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import TextField from "@mui/material/TextField";
import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import Paper from "@mui/material/Paper";
import IconButton from "@mui/material/IconButton";
import SendIcon from "@mui/icons-material/Send";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ChatIcon from "@mui/icons-material/Chat";
import PageHeader from "@/components/PageHeader";
import { useProject } from "@/components/ProjectContext";
import { api } from "@/lib/api";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface KPI {
  label: string;
  value_a: number;
  value_b: number;
  unit: string;
  commentary: string;
}

interface AIDashboard {
  executive_summary: string;
  key_findings: string[];
  recommendations: string[];
  kpis: KPI[];
  charts: { title: string; insight: string; data: any[]; layout: any }[];
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export default function AIInsightsPage() {
  const { projectId, runId } = useProject();
  const [dashboard, setDashboard] = React.useState<AIDashboard | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [chatMessages, setChatMessages] = React.useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = React.useState("");
  const [chatLoading, setChatLoading] = React.useState(false);
  const chatEndRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  async function handleGenerateDashboard() {
    if (!runId) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.post("/ai-insights/dashboard", {
        project_id: projectId,
        run_id: runId,
      }, { timeout: 120000 });
      setDashboard(data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e.message || "AI generation failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleChatSend() {
    if (!chatInput.trim() || !runId) return;
    const userMsg: ChatMessage = { role: "user", content: chatInput.trim() };
    const newMessages = [...chatMessages, userMsg];
    setChatMessages(newMessages);
    setChatInput("");
    setChatLoading(true);
    try {
      const { data } = await api.post("/ai-insights/chat", {
        project_id: projectId,
        run_id: runId,
        messages: newMessages,
      }, { timeout: 120000 });
      setChatMessages([...newMessages, { role: "assistant", content: data.answer }]);
    } catch (e: any) {
      setChatMessages([...newMessages, {
        role: "assistant",
        content: `Error: ${e?.response?.data?.detail || e.message || "AI request failed"}`
      }]);
    } finally {
      setChatLoading(false);
    }
  }

  return (
    <Box>
      <PageHeader
        title="AI Executive Insights"
        subtitle="Generate AI-powered executive dashboards and ask supply chain analysis questions using GPT-4o"
      />

      {/* Generate Dashboard Section */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 2 }}>
            <AutoAwesomeIcon sx={{ color: "primary.main" }} />
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                AI Executive Dashboard
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Generate an executive summary, KPIs, and charts from your validated pipeline data using GPT-4o.
                Requires an active run with Phase 3 completed.
              </Typography>
            </Box>
            <Box sx={{ ml: "auto" }}>
              <Button
                variant="contained"
                startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <AutoAwesomeIcon />}
                onClick={handleGenerateDashboard}
                disabled={loading || !runId}
              >
                {loading ? "Generating..." : "Generate AI Dashboard"}
              </Button>
            </Box>
          </Box>

          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {dashboard && (
            <>
              {/* Executive Summary */}
              <Paper variant="outlined" sx={{ p: 2, mb: 3, bgcolor: "#F0F5FF" }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600, color: "primary.main", mb: 1 }}>
                  Executive Summary
                </Typography>
                <Typography variant="body2">{dashboard.executive_summary}</Typography>
              </Paper>

              {/* KPIs */}
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Key Performance Indicators</Typography>
              <Grid container spacing={2} sx={{ mb: 3 }}>
                {(dashboard.kpis || []).map((kpi, i) => (
                  <Grid item xs={12} sm={6} md={4} key={i}>
                    <Card variant="outlined">
                      <CardContent sx={{ pb: "12px !important" }}>
                        <Typography variant="caption" color="text.secondary">{kpi.label}</Typography>
                        <Box sx={{ display: "flex", gap: 2, mt: 0.5 }}>
                          <Typography variant="h6" sx={{ color: "primary.main", fontWeight: 700 }}>
                            {kpi.unit === "$" ? `$${(kpi.value_a / 1e6).toFixed(1)}M` : `${kpi.value_a}${kpi.unit}`}
                          </Typography>
                        </Box>
                        <Typography variant="caption" color="text.secondary">{kpi.commentary}</Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                ))}
              </Grid>

              {/* Charts */}
              {(dashboard.charts || []).length > 0 && (
                <>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Analytics Charts</Typography>
                  <Grid container spacing={2} sx={{ mb: 3 }}>
                    {dashboard.charts.map((chart, i) => (
                      <Grid item xs={12} md={6} key={i}>
                        <Card variant="outlined">
                          <CardContent>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, color: "primary.main" }}>
                              {chart.title}
                            </Typography>
                            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                              {chart.insight}
                            </Typography>
                            <Plot
                              data={chart.data || []}
                              layout={{ ...chart.layout, autosize: true, height: 320, margin: { t: 20, b: 40 } }}
                              style={{ width: "100%" }}
                              useResizeHandler
                              config={{ displayModeBar: false }}
                            />
                          </CardContent>
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                </>
              )}

              {/* Key Findings + Recommendations */}
              <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Key Findings</Typography>
                  {(dashboard.key_findings || []).map((f, i) => (
                    <Typography key={i} variant="body2" sx={{ mb: 0.5 }}>• {f}</Typography>
                  ))}
                </Grid>
                <Grid item xs={12} md={6}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>Recommendations</Typography>
                  {(dashboard.recommendations || []).map((r, i) => (
                    <Typography key={i} variant="body2" sx={{ mb: 0.5 }}>• {r}</Typography>
                  ))}
                </Grid>
              </Grid>
            </>
          )}
        </CardContent>
      </Card>

      {/* Chat Section */}
      <Card>
        <CardContent>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 2 }}>
            <ChatIcon sx={{ color: "primary.main" }} />
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                AI Supply Chain Analyst Chat
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Ask questions about your data — root-cause analysis, cost drivers, flow volumes, and more.
              </Typography>
            </Box>
          </Box>
          <Divider sx={{ mb: 2 }} />

          {/* Chat history */}
          <Box sx={{ minHeight: 200, maxHeight: 400, overflowY: "auto", mb: 2, px: 1 }}>
            {chatMessages.length === 0 ? (
              <Typography color="text.secondary" variant="body2" sx={{ textAlign: "center", mt: 4 }}>
                Ask anything about your supply chain data — e.g. "What are the top cost drivers?" or "Which locations have the highest outbound volume?"
              </Typography>
            ) : (
              chatMessages.map((msg, i) => (
                <Box
                  key={i}
                  sx={{
                    display: "flex",
                    justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                    mb: 1.5,
                  }}
                >
                  <Paper
                    elevation={0}
                    sx={{
                      p: 1.5,
                      maxWidth: "80%",
                      bgcolor: msg.role === "user" ? "primary.main" : "#F3F4F6",
                      color: msg.role === "user" ? "#fff" : "text.primary",
                      borderRadius: msg.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                      fontSize: 13,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {msg.content}
                  </Paper>
                </Box>
              ))
            )}
            {chatLoading && (
              <Box sx={{ display: "flex", justifyContent: "flex-start", mb: 1 }}>
                <Paper elevation={0} sx={{ p: 1.5, bgcolor: "#F3F4F6", borderRadius: "12px 12px 12px 2px" }}>
                  <CircularProgress size={16} />
                </Paper>
              </Box>
            )}
            <div ref={chatEndRef} />
          </Box>

          {/* Input */}
          <Box sx={{ display: "flex", gap: 1 }}>
            <TextField
              fullWidth
              size="small"
              placeholder="Ask a supply chain analysis question..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleChatSend(); } }}
              disabled={chatLoading || !runId}
            />
            <IconButton
              color="primary"
              onClick={handleChatSend}
              disabled={chatLoading || !chatInput.trim() || !runId}
            >
              <SendIcon />
            </IconButton>
          </Box>
          {!runId && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              Run the pipeline first to enable AI chat.
            </Typography>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
