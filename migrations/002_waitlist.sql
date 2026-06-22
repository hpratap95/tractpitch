-- Waitlist table for Pro plan email capture
-- Run: psql -U tractpitch tractpitch < migrations/002_waitlist.sql

CREATE TABLE IF NOT EXISTS public.waitlist (
    id         SERIAL PRIMARY KEY,
    email      VARCHAR(254) NOT NULL UNIQUE,
    source     VARCHAR(50)  NOT NULL DEFAULT 'pro_landing',
    signed_up_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_waitlist_email ON public.waitlist(email);
