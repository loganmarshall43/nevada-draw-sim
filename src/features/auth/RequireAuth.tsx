import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export default function RequireAuth() {
  const { user, loading } = useAuth();

  if (loading) return <div style={{ padding: 24 }}>Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;

  return <Outlet />;
}