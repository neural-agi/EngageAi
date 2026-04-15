const API_URL = "https://engageai-production-8faa.up.railway.app";


export async function getHealth() {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  return res.json();
}


export async function getRoot() {
  const res = await fetch(`${API_URL}/`, { cache: "no-store" });
  return res.json();
}
