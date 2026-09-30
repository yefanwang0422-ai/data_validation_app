"use client";

import { createTheme } from "@mui/material/styles";

/**
 * Professional "enterprise SaaS" blue theme.
 *
 * Palette:
 *  - primary:   deep corporate navy blue
 *  - secondary: medium blue (interactive accents, active nav)
 *  - info/highlight: lighter sky blue (chart accents, badges)
 *  - neutral grays for backgrounds and card surfaces
 */
const theme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: "#0B3D91", // deep navy blue
      light: "#2D5FB3",
      dark: "#082B66",
      contrastText: "#FFFFFF",
    },
    secondary: {
      main: "#2D6CDF", // medium blue
      light: "#5B9BD5",
      dark: "#1E4FAE",
      contrastText: "#FFFFFF",
    },
    info: {
      main: "#5B9BD5", // light sky blue accent
    },
    success: {
      main: "#1E8E63",
    },
    warning: {
      main: "#D9822B",
    },
    error: {
      main: "#C1372B",
    },
    background: {
      default: "#F4F7FB",
      paper: "#FFFFFF",
    },
    text: {
      primary: "#0F1E3D",
      secondary: "#4A5A78",
    },
    divider: "#DCE4F0",
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Segoe UI", Arial, sans-serif',
    h1: { fontWeight: 700 },
    h2: { fontWeight: 700 },
    h3: { fontWeight: 600 },
    h4: { fontWeight: 600 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    subtitle1: { fontWeight: 500 },
    button: { fontWeight: 600, textTransform: "none" },
  },
  shape: {
    borderRadius: 10,
  },
  components: {
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: "#0B3D91",
          boxShadow: "0 2px 8px rgba(11,61,145,0.25)",
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: "#0F2A5C",
          color: "#E7EDF9",
          borderRight: "none",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          boxShadow: "0 1px 4px rgba(15,30,61,0.08)",
          border: "1px solid #E3E9F5",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 600,
        },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          backgroundColor: "#EEF3FC",
        },
      },
    },
  },
});

export default theme;

// Blue color sequence for charts, consistent across the app.
export const CHART_BLUE_SEQUENCE = [
  "#0B3D91",
  "#2D6CDF",
  "#5B9BD5",
  "#7FB2E5",
  "#A9CBEF",
  "#0F2A5C",
  "#1E4FAE",
  "#3E7BD1",
];
