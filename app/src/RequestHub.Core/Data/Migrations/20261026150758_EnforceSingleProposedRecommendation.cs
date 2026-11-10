using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RequestHub.Core.Data.Migrations
{
    /// <inheritdoc />
    public partial class EnforceSingleProposedRecommendation : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                """
                WITH ranked AS (
                    SELECT "Id", ROW_NUMBER() OVER (PARTITION BY "RequestId" ORDER BY "CreatedAt" DESC, "Id" DESC) AS position
                    FROM "Recommendations"
                    WHERE "Status" = 'Proposed'
                )
                UPDATE "Recommendations" AS recommendation
                SET "Status" = 'Superseded'
                FROM ranked
                WHERE recommendation."Id" = ranked."Id" AND ranked.position > 1;
                """);

            migrationBuilder.CreateIndex(
                name: "IX_Recommendations_RequestId_Proposed",
                table: "Recommendations",
                column: "RequestId",
                unique: true,
                filter: "\"Status\" = 'Proposed'");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_Recommendations_RequestId_Proposed",
                table: "Recommendations");
        }
    }
}
