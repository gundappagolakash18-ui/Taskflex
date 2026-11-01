import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { AppSuspenseFallback, GuestOnly, HomeRedirect, RequireRole } from "@/components/routing";
import { PageLoader } from "@/components/ui";

// Public
const Home = lazy(() => import("@/pages/Home"));
const Login = lazy(() => import("@/pages/auth/Login"));
const Register = lazy(() => import("@/pages/auth/Register"));
const ForgotPassword = lazy(() => import("@/pages/auth/ForgotPassword"));
const ResetPassword = lazy(() => import("@/pages/auth/ResetPassword"));
const VerifyEmail = lazy(() => import("@/pages/auth/VerifyEmail"));
const PublicTrack = lazy(() => import("@/pages/public/PublicTrack"));

// Customer
const CustomerLayout = lazy(() => import("@/pages/customer/CustomerLayout"));
const CustomerDashboard = lazy(() => import("@/pages/customer/Dashboard"));
const CreateTask = lazy(() => import("@/pages/customer/CreateTask"));
const TaskDetails = lazy(() => import("@/pages/shared/TaskDetails"));
const BrowseWorkers = lazy(() => import("@/pages/customer/BrowseWorkers"));
const WorkerProfile = lazy(() => import("@/pages/customer/WorkerProfile"));
const Wallet = lazy(() => import("@/pages/shared/Wallet"));
const Profile = lazy(() => import("@/pages/shared/Profile"));
const Tasks = lazy(() => import("@/pages/shared/Tasks"));

// Worker
const WorkerLayout = lazy(() => import("@/pages/worker/WorkerLayout"));
const WorkerDashboard = lazy(() => import("@/pages/worker/Dashboard"));
const WorkerOffers = lazy(() => import("@/pages/worker/Offers"));
const WorkerScheduledBoard = lazy(() => import("@/pages/worker/ScheduledBoard"));
const WorkerEarnings = lazy(() => import("@/pages/worker/Earnings"));
const WorkerReviews = lazy(() => import("@/pages/worker/Reviews"));
const WorkerSettings = lazy(() => import("@/pages/worker/Settings"));

// Shared (authenticated)
const Messages = lazy(() => import("@/pages/shared/Messages"));
const Notifications = lazy(() => import("@/pages/shared/Notifications"));

// Admin
const AdminLayout = lazy(() => import("@/pages/admin/AdminLayout"));
const AdminDashboard = lazy(() => import("@/pages/admin/Dashboard"));
const AdminUsers = lazy(() => import("@/pages/admin/Users"));
const AdminWorkers = lazy(() => import("@/pages/admin/Workers"));
const AdminVerifications = lazy(() => import("@/pages/admin/Verifications"));
const AdminTasks = lazy(() => import("@/pages/admin/Tasks"));
const AdminPayments = lazy(() => import("@/pages/admin/Payments"));
const AdminDisputes = lazy(() => import("@/pages/admin/Disputes"));
const AdminReports = lazy(() => import("@/pages/admin/Reports"));
const AdminSettings = lazy(() => import("@/pages/admin/Settings"));
const AdminAudit = lazy(() => import("@/pages/admin/AuditLogs"));
const AdminSosAlerts = lazy(() => import("@/pages/admin/SosAlerts"));
const AdminRideCheck = lazy(() => import("@/pages/admin/RideCheck"));
const NotFound = lazy(() => import("@/pages/NotFound"));

function suspend(node: React.ReactNode) {
  return <Suspense fallback={<PageLoader />}>{node}</Suspense>;
}

export default function App() {
  return (
    <Suspense fallback={<AppSuspenseFallback />}>
      <Routes>
        <Route element={<GuestOnly />}>
          <Route path="/login" element={suspend(<Login />)} />
          <Route path="/register" element={suspend(<Register />)} />
          <Route path="/forgot-password" element={suspend(<ForgotPassword />)} />
          <Route path="/reset-password" element={suspend(<ResetPassword />)} />
          <Route path="/verify-email" element={suspend(<VerifyEmail />)} />
        </Route>

        <Route path="/" element={suspend(<Home />)} />
        <Route path="/track/:token" element={suspend(<PublicTrack />)} />

        {/* Customer */}
        <Route element={<RequireRole roles={["CUSTOMER"]} />}>
          <Route path="/app" element={suspend(<CustomerLayout />)}>
            <Route index element={suspend(<CustomerDashboard />)} />
            <Route path="new" element={suspend(<CreateTask />)} />
            <Route path="tasks" element={suspend(<Tasks />)} />
            <Route path="tasks/:taskId" element={suspend(<TaskDetails />)} />
            <Route path="runners" element={suspend(<BrowseWorkers />)} />
            <Route path="runners/:workerId" element={suspend(<WorkerProfile />)} />
            <Route path="messages" element={suspend(<Messages />)} />
            <Route path="wallet" element={suspend(<Wallet />)} />
            <Route path="notifications" element={suspend(<Notifications />)} />
            <Route path="profile" element={suspend(<Profile />)} />
          </Route>
        </Route>

        {/* Worker */}
        <Route element={<RequireRole roles={["WORKER"]} />}>
          <Route path="/worker" element={suspend(<WorkerLayout />)}>
            <Route index element={suspend(<WorkerDashboard />)} />
            <Route path="offers" element={suspend(<WorkerOffers />)} />
            <Route path="scheduled" element={suspend(<WorkerScheduledBoard />)} />
            <Route path="tasks/:taskId" element={suspend(<TaskDetails />)} />
            <Route path="earnings" element={suspend(<WorkerEarnings />)} />
            <Route path="reviews" element={suspend(<WorkerReviews />)} />
            <Route path="messages" element={suspend(<Messages />)} />
            <Route path="notifications" element={suspend(<Notifications />)} />
            <Route path="settings" element={suspend(<WorkerSettings />)} />
          </Route>
        </Route>

        {/* Admin */}
        <Route element={<RequireRole roles={["ADMIN"]} />}>
          <Route path="/admin" element={suspend(<AdminLayout />)}>
            <Route index element={suspend(<AdminDashboard />)} />
            <Route path="users" element={suspend(<AdminUsers />)} />
            <Route path="workers" element={suspend(<AdminWorkers />)} />
            <Route path="verifications" element={suspend(<AdminVerifications />)} />
            <Route path="tasks" element={suspend(<AdminTasks />)} />
            <Route path="payments" element={suspend(<AdminPayments />)} />
            <Route path="disputes" element={suspend(<AdminDisputes />)} />
            <Route path="sos" element={suspend(<AdminSosAlerts />)} />
            <Route path="ridecheck" element={suspend(<AdminRideCheck />)} />
            <Route path="reports" element={suspend(<AdminReports />)} />
            <Route path="settings" element={suspend(<AdminSettings />)} />
            <Route path="audit-logs" element={suspend(<AdminAudit />)} />
          </Route>
        </Route>

        <Route path="/dashboard" element={<HomeRedirect />} />
        <Route path="*" element={suspend(<NotFound />)} />
      </Routes>
    </Suspense>
  );
}
