import { useEffect, useId, useRef, useState } from "react";
import { geocode } from "../lib/api.js";

/** Text input with place suggestions. `value` is {label, lat, lon} or null. */
export default function PlaceInput({ label, value, onChange, placeholder, autoFocus }) {
  const [text, setText] = useState(value?.label ?? "");
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [status, setStatus] = useState("");
  const listId = useId();
  const inputId = useId();
  const abort = useRef(null);

  // Sync the text when a place is chosen from outside (e.g. an example trip).
  useEffect(() => {
    if (value) setText(value.label);
  }, [value]);

  useEffect(() => {
    if (!open) return;
    const q = text.trim();
    if (q.length < 2 || q === value?.label) {
      setItems([]);
      return;
    }
    const timer = setTimeout(async () => {
      abort.current?.abort();
      abort.current = new AbortController();
      setStatus("Searching…");
      try {
        const res = await geocode(q, abort.current.signal);
        setItems(res);
        setActive(res.length ? 0 : -1);
        setStatus(res.length ? "" : "No matches. Try a city and state, or “lat, lon”.");
      } catch (e) {
        if (e.name !== "AbortError") setStatus(e.message);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [text, open, value]);

  const choose = (item) => {
    onChange(item);
    setText(item.label);
    setOpen(false);
    setItems([]);
    setStatus("");
  };

  const onKeyDown = (e) => {
    if (!open || !items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + items.length) % items.length);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(items[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="field place">
      <label htmlFor={inputId}>{label}</label>
      <input
        id={inputId}
        type="text"
        role="combobox"
        aria-expanded={open && items.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        autoFocus={autoFocus}
        placeholder={placeholder}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          if (value) onChange(null);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {open && (items.length > 0 || status) && (
        <ul className="suggestions" id={listId} role="listbox">
          {items.map((it, i) => (
            <li
              key={`${it.lat},${it.lon},${i}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(it);
              }}
              onMouseEnter={() => setActive(i)}
            >
              {it.label}
            </li>
          ))}
          {!items.length && status && <li className="status">{status}</li>}
        </ul>
      )}
    </div>
  );
}
