import { Link } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";
import { TASK_TYPE_ICONS, TASK_TYPE_LABELS } from "@/lib/constants";
import type { TaskType } from "@/types";

const HOW_IT_WORKS = [
  {
    title: "Describe your errand",
    body: "Type it the way you'd tell a friend — “submit my property papers at the sub-registrar office tomorrow morning, budget ₹350”.",
  },
  {
    title: "AI drafts the details",
    body: "TaskFlex reads your request, structures it into a task and shows you exactly what it understood. You edit anything before it goes live.",
  },
  {
    title: "You confirm, we match",
    body: "Only after your confirmation do we notify verified runners near the location — ranked by distance, skills, rating and reliability.",
  },
  {
    title: "Track, pay, rate",
    body: "Follow the runner live, chat in-app, and release payment only when you confirm the errand is done. Then rate each other.",
  },
];

const TASK_TYPES: TaskType[] = [
  "appointment_assistance",
  "queue_standing",
  "government_office",
  "document_submission",
  "parcel_collection",
  "grocery_pickup",
  "bank_assistance",
];

export default function Home() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="min-h-screen bg-white">
      <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3.5">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary-600 text-lg font-black text-white">T</span>
            <span className="text-lg font-extrabold tracking-tight text-slate-900">
              Task<span className="text-primary-600">Flex</span>
            </span>
          </Link>
          <nav className="flex items-center gap-2">
            {user ? (
              <Link to={user.role === "ADMIN" ? "/admin" : user.role === "WORKER" ? "/worker" : "/app"} className="btn-primary">
                Open app
              </Link>
            ) : (
              <>
                <Link to="/login" className="btn-ghost hidden sm:inline-flex">
                  Sign in
                </Link>
                <Link to="/register" className="btn-primary">
                  Get started
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl gap-10 px-4 pb-16 pt-12 sm:pt-20 lg:grid-cols-2 lg:items-center">
          <div>
            <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-accent-50 px-3 py-1 text-xs font-semibold text-accent-700">
              ✨ AI-understands, you confirm — errands in your city
            </p>
            <h1 className="text-4xl font-black leading-tight tracking-tight text-slate-900 sm:text-5xl">
              Real errands, handled by <span className="text-primary-600">real people</span>.
            </h1>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-slate-600 sm:text-lg">
              Hospital registrations. Standing in government-office queues. Document drop-offs and parcel pickups.
              Describe it in plain words — TaskFlex parses it, confirms it with you, and sends it to verified
              runners nearby.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link to={user ? (user.role === "CUSTOMER" ? "/app/new" : user.role === "WORKER" ? "/worker" : "/admin") : "/register"} className="btn-primary px-6 py-3 text-base">
                Post an errand
              </Link>
              <Link to="/register?role=WORKER" className="btn-secondary px-6 py-3 text-base">
                Become a runner
              </Link>
            </div>
            <p className="mt-4 text-xs text-slate-400">
              Free to join · Runners are ID-verified · You approve every errand before it&apos;s dispatched
            </p>
          </div>

          <div className="relative">
            <div className="card animate-slide-up space-y-4 p-6">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">You type</p>
              <p className="rounded-xl bg-slate-50 p-4 text-sm leading-relaxed text-slate-700">
                “Need someone to submit my property tax documents at the Belagavi corporation office
                tomorrow 11am. Budget ₹300.”
              </p>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">TaskFlex understands</p>
              <div className="space-y-2 rounded-xl border border-primary-100 bg-primary-50/60 p-4 text-sm">
                <p className="font-semibold text-slate-800">Document submission · Government office</p>
                <p className="text-slate-600">📍 Belagavi corporation office · 🕐 tomorrow, 11:00</p>
                <p className="text-slate-600">💰 ₹300 · ⏱ ~60 min · documents_handling skill</p>
                <p className="flex items-center gap-1.5 text-xs font-medium text-primary-700">
                  <span className="inline-block h-2 w-2 rounded-full bg-primary-500" />
                  91% confidence — edit anything, then confirm to dispatch
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="border-y border-slate-100 bg-slate-50 py-16">
          <div className="mx-auto max-w-6xl px-4">
            <h2 className="text-2xl font-bold text-slate-900 sm:text-3xl">Errands we handle</h2>
            <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
              {(TASK_TYPES as TaskType[]).map((t) => (
                <div key={t} className="card flex flex-col items-center gap-2 p-4 text-center transition-shadow hover:shadow-md">
                  <span className="text-3xl">{TASK_TYPE_ICONS[t]}</span>
                  <span className="text-xs font-semibold text-slate-700">{TASK_TYPE_LABELS[t]}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-16">
          <h2 className="text-2xl font-bold text-slate-900 sm:text-3xl">How it works</h2>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {HOW_IT_WORKS.map((step, i) => (
              <div key={step.title} className="card p-5">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-600 text-sm font-bold text-white">
                  {i + 1}
                </span>
                <h3 className="mt-3 font-semibold text-slate-900">{step.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{step.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 pb-20">
          <div className="rounded-3xl bg-primary-700 px-6 py-12 text-center sm:px-12">
            <h2 className="text-2xl font-bold text-white sm:text-3xl">Your time is worth more than a queue.</h2>
            <p className="mx-auto mt-3 max-w-xl text-primary-100">
              Join as a customer to delegate errands, or as a verified runner to earn on your own schedule.
            </p>
            <div className="mt-7 flex flex-wrap justify-center gap-3">
              <Link to="/register" className="btn bg-white px-6 py-3 text-base text-primary-700 hover:bg-primary-50">
                Create an account
              </Link>
              <Link to="/login" className="btn border border-primary-300 px-6 py-3 text-base text-white hover:bg-primary-600">
                Sign in
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-100 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-4 text-sm text-slate-400 sm:flex-row">
          <p>© 2026 TaskFlex. All rights reserved.</p>
          <p>Real errands, handled by real people.</p>
        </div>
      </footer>
    </div>
  );
}
