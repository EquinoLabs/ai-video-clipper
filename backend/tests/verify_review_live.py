"""Live verification script for Phase 3 review API endpoints."""

import sys
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from app.main import app

def main():
    client = TestClient(app)
    
    # 1. Test listing runs
    print("Testing GET /api/v1/review/runs...")
    runs_res = client.get("/api/v1/review/runs")
    print(f"Status: {runs_res.status_code}")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    print(f"Found {len(runs)} run(s)")
    for r in runs:
        print(f"  - Run: {r['run_id']}")
        print(f"    Source: {r['source_filename']} ({r['source_duration_seconds']:.1f}s)")
        print(f"    Candidates: {r['total_candidates']}, Rendered: {r['rendered_candidates']}")

    if not runs:
        print("No runs available to verify details.")
        return

    # 2. Test getting run details for run with candidates
    target_run = next((r for r in runs if r["rendered_candidates"] > 0), runs[0])
    run_id = target_run["run_id"]
    print(f"\nTesting GET /api/v1/review/runs/{run_id}...")
    detail_res = client.get(f"/api/v1/review/runs/{run_id}")
    print(f"Status: {detail_res.status_code}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    candidates = detail["candidates"]
    print(f"Run has {len(candidates)} candidate(s)")

    if candidates:
        first_cand = candidates[0]
        print(f"  Candidate: {first_cand['id']}")
        print(f"  Hook: {first_cand['hook']}")
        print(f"  Duration: {first_cand['duration_seconds']:.1f}s")
        print(f"  Overall Score: {first_cand['overall_score']}")
        print(f"  Is Rendered: {first_cand['render_info']['is_rendered']}")

        # 3. Test video streaming & download if rendered
        if first_cand["render_info"]["is_rendered"]:
            video_url = first_cand["render_info"]["video_url"]
            download_url = first_cand["render_info"]["download_url"]
            print(f"\nTesting video stream URL: {video_url}...")
            v_res = client.get(video_url)
            print(f"Video Stream Status: {v_res.status_code}")
            print(f"Content-Type: {v_res.headers.get('content-type')}")
            print(f"Content-Length: {len(v_res.content)} bytes")
            assert v_res.status_code == 200
            assert v_res.headers.get("content-type") == "video/mp4"
            assert len(v_res.content) > 10000

            print(f"\nTesting download URL: {download_url}...")
            dl_res = client.get(download_url)
            print(f"Download Status: {dl_res.status_code}")
            print(f"Content-Disposition: {dl_res.headers.get('content-disposition')}")
            assert dl_res.status_code == 200
            assert "attachment" in dl_res.headers.get("content-disposition", "") or "filename" in dl_res.headers.get("content-disposition", "")

    # 4. Verify path traversal security
    print("\nTesting path traversal rejection...")
    bad_res1 = client.get(f"/api/v1/review/runs/..%2F..%2Fetc/passwd")
    print(f"Path traversal status (..): {bad_res1.status_code}")
    assert bad_res1.status_code in (400, 403, 404)

    bad_res2 = client.get(f"/api/v1/review/runs/{run_id}/media/..%2Fsecret.txt")
    print(f"Media path traversal status: {bad_res2.status_code}")
    assert bad_res2.status_code in (400, 403, 404)

    print("\n[SUCCESS] ALL LIVE REVIEW CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
