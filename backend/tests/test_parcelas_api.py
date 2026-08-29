"""Integration tests for /api/parcelas CRUD endpoints."""


PARCELA_PAYLOAD = {
    "id": "p001",
    "nombre": "Cabaña del Lago",
    "tipo": "cabaña",
    "tamano": "40m2",
    "predio": "Almafuerte",
}


class TestParcelasCRUD:
    """Full CRUD lifecycle for parcelas."""

    def test_list_parcelas_empty(self, test_client):
        """GET /api/parcelas returns empty list when no parcelas exist."""
        resp = test_client.get("/api/parcelas")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_parcela(self, test_client):
        """POST /api/parcelas creates a parcela with 201."""
        resp = test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "p001"
        assert body["nombre"] == "Cabaña del Lago"
        assert body["tipo"] == "cabaña"
        assert body["predio"] == "Almafuerte"

    def test_get_parcela(self, test_client):
        """GET /api/parcelas/{id} returns the created parcela."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        resp = test_client.get("/api/parcelas/p001")
        assert resp.status_code == 200
        assert resp.json()["id"] == "p001"
        assert resp.json()["nombre"] == "Cabaña del Lago"

    def test_get_parcela_nonexistent_returns_404(self, test_client):
        """GET /api/parcelas/{id} returns 404 for non-existent id."""
        resp = test_client.get("/api/parcelas/nonexistent")
        assert resp.status_code == 404

    def test_update_parcela(self, test_client):
        """PUT /api/parcelas/{id} updates the parcela."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        resp = test_client.put(
            "/api/parcelas/p001",
            json={"nombre": "Cabaña del Sol", "tamano": "60m2"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["nombre"] == "Cabaña del Sol"
        assert body["tamano"] == "60m2"
        # Unchanged fields stay the same
        assert body["tipo"] == "cabaña"
        assert body["predio"] == "Almafuerte"

    def test_update_parcela_nonexistent_returns_404(self, test_client):
        """PUT /api/parcelas/{id} returns 404 for non-existent id."""
        resp = test_client.put(
            "/api/parcelas/nonexistent", json={"nombre": "Nope"}
        )
        assert resp.status_code == 404

    def test_delete_parcela(self, test_client):
        """DELETE /api/parcelas/{id} returns 204 and removes parcela."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        resp = test_client.delete("/api/parcelas/p001")
        assert resp.status_code == 204
        # Verify gone
        resp = test_client.get("/api/parcelas/p001")
        assert resp.status_code == 404

    def test_delete_parcela_nonexistent_returns_404(self, test_client):
        """DELETE /api/parcelas/{id} returns 404 for non-existent id."""
        resp = test_client.delete("/api/parcelas/nonexistent")
        assert resp.status_code == 404

    def test_list_parcelas_filter_by_predio(self, test_client):
        """GET /api/parcelas?predio=Embalse filters by predio."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        test_client.post(
            "/api/parcelas",
            json={
                **PARCELA_PAYLOAD,
                "id": "p002",
                "nombre": "Balsa Norte",
                "tipo": "balsa",
                "predio": "Embalse",
            },
        )
        resp = test_client.get("/api/parcelas", params={"predio": "Embalse"})
        assert resp.status_code == 200
        parcelas = resp.json()
        assert len(parcelas) == 1
        assert parcelas[0]["id"] == "p002"
        assert parcelas[0]["predio"] == "Embalse"

    def test_list_parcelas_returns_all_when_no_filter(self, test_client):
        """GET /api/parcelas returns all parcelas when no predio filter."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        test_client.post(
            "/api/parcelas",
            json={
                **PARCELA_PAYLOAD,
                "id": "p002",
                "nombre": "Balsa Norte",
                "tipo": "balsa",
                "predio": "Embalse",
            },
        )
        resp = test_client.get("/api/parcelas")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
