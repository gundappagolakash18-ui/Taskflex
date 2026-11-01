import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4 text-center">
      <p className="text-7xl font-black text-primary-600">404</p>
      <h1 className="mt-3 text-xl font-bold text-slate-900">This page wandered off mid-errand</h1>
      <p className="mt-2 max-w-sm text-sm text-slate-500">
        The link may be broken, or the page may have moved. Let's get you back on track.
      </p>
      <Link to="/" className="btn-primary mt-6">
        Back to home
      </Link>
    </div>
  );
}
