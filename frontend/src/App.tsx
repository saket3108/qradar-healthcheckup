import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAppSelector } from "@/store/hooks";
import { can, type Perm } from "@/store/auth";
import AppShell from "@/components/AppShell";
import { LoadingGrid } from "@/components/common";
import Login from "@/pages/Login";
import Assessments from "@/pages/Assessments";
import AssessmentLayout from "@/pages/AssessmentLayout";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Overview = lazy(() => import("@/pages/Overview"));
const Deployment = lazy(() => import("@/pages/Deployment"));
const Notifications = lazy(() => import("@/pages/Notifications"));
const LogSources = lazy(() => import("@/pages/LogSources"));
const Applications = lazy(() => import("@/pages/Applications"));
const Performance = lazy(() => import("@/pages/Performance"));
const Licensing = lazy(() => import("@/pages/Licensing"));
const HealthScore = lazy(() => import("@/pages/HealthScore"));
const Assistant = lazy(() => import("@/pages/Assistant"));
const ReportBuilder = lazy(() => import("@/pages/ReportBuilder"));
const Admin = lazy(() => import("@/pages/Admin"));

export function RequireAuth({ children, perm }: { children: React.ReactNode; perm?: Perm }) {
  const { token, user } = useAppSelector((s) => s.auth);
  const loc = useLocation();
  if (!token || !user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (perm && !can(user.role, perm)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<Assessments />} />
        <Route path="admin" element={<RequireAuth perm="audit"><Suspense fallback={<LoadingGrid />}><Admin /></Suspense></RequireAuth>} />
        <Route path="assessments/:id" element={<AssessmentLayout />}>
          <Route index element={<Suspense fallback={<LoadingGrid />}><Dashboard /></Suspense>} />
          <Route path="overview" element={<Suspense fallback={<LoadingGrid />}><Overview /></Suspense>} />
          <Route path="deployment" element={<Suspense fallback={<LoadingGrid />}><Deployment /></Suspense>} />
          <Route path="notifications" element={<Suspense fallback={<LoadingGrid />}><Notifications /></Suspense>} />
          <Route path="logsources" element={<Suspense fallback={<LoadingGrid />}><LogSources /></Suspense>} />
          <Route path="applications" element={<Suspense fallback={<LoadingGrid />}><Applications /></Suspense>} />
          <Route path="performance" element={<Suspense fallback={<LoadingGrid />}><Performance /></Suspense>} />
          <Route path="licensing" element={<Suspense fallback={<LoadingGrid />}><Licensing /></Suspense>} />
          <Route path="health" element={<Suspense fallback={<LoadingGrid />}><HealthScore /></Suspense>} />
          <Route path="assistant" element={<Suspense fallback={<LoadingGrid />}><Assistant /></Suspense>} />
          <Route path="report" element={<Suspense fallback={<LoadingGrid />}><ReportBuilder /></Suspense>} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
