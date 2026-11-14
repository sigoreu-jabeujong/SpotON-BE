from typing import Self

from pydantic import PrivateAttr, model_validator

from app.schemas.chains import ChainRiskQuery
from app.schemas.interpret import InterpretHistory, InterpretModel
from app.schemas.stores import HistoryQuery


class ChainInterpretRequest(InterpretModel):
    query: ChainRiskQuery
    history: InterpretHistory | None = None
    _history_query: HistoryQuery | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def canonical_history(self) -> Self:
        if self.history is not None:
            self._history_query = HistoryQuery(
                building_key=self.history.building_key,
                floor_unit=self.history.floor_unit,
                category=self.query.category,
            )
        return self

    def history_query(self) -> HistoryQuery | None:
        return self._history_query
